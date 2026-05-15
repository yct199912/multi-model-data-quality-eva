# services/model/src/core/providers/gemma4.py
import asyncio
import json
import logging
import threading
from .base import BaseEvalProvider
from ...config import settings

OUTPUT_FORMAT_PROMPT = """完成之后只返回JSON，不要重复规则和解释。格式：{"score": 分数, "eva_content": "评价"}，分数为0到100的数字，评价用中文简短描述。"""

GEMMA4_CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "<start_of_turn>{{ message.role }}\n"
    "{% if message.content is string %}"
    "{{ message.content }}\n"
    "{% else %}"
    "{% for content in message.content %}"
    "{% if content.type == 'image' %}"
    "<image>\n"
    "{% elif content.type == 'text' %}"
    "{{ content.text }}\n"
    "{% endif %}"
    "{% endfor %}"
    "{% endif %}"
    "<end_of_turn>\n"
    "{% endfor %}"
    "{% if add_generation_prompt %}"
    "<start_of_turn>model\n"
    "{% endif %}"
)

logger = logging.getLogger(__name__)


class Gemma4EvalProvider(BaseEvalProvider):
    """使用 gemma-4-e4b 模型进行数据质量评价。

    模型通过 ModelScope 下载，支持 CPU / GPU / NPU。
    使用 float16 精度，约 8GB 内存。
    """

    _init_lock = threading.Lock()
    # Keys produced by image_processor that model.generate() does not accept
    _IGNORED_INPUT_KEYS = {"num_soft_tokens_per_image", "num_soft_tokens_per_video"}

    def __init__(self, model_name: str = None, device: str = None, cache_dir: str = None):
        self.model_name = model_name or settings.model_name
        self.device = device or settings.device
        self.cache_dir = cache_dir or settings.model_cache_dir
        self._processor = None
        self._model = None
        self._initialized = False

    def _init_model(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._do_init_model()

    def _do_init_model(self):
        import os
        if self.cache_dir:
            os.environ["MODELSCOPE_CACHE"] = self.cache_dir

        logger.info(f"Starting to download and load model: {self.model_name}, device={self.device}")

        from modelscope import snapshot_download
        try:
            model_source = snapshot_download(self.model_name)
        except Exception as e:
            logger.warning(f"ModelScope download with original name failed: {e}, trying AI-ModelScope mirror")
            local_name = self.model_name.split("/")[-1]
            model_source = snapshot_download(f"AI-ModelScope/{local_name}")

        logger.info(f"Model downloaded to: {model_source}")

        from transformers import AutoTokenizer, AutoProcessor, AutoModelForCausalLM
        import torch
        import json

        # 修复 tokenizer_config.json 中 extra_special_tokens 为 list 时的兼容性问题
        # gemma-4-e4b 模型的 tokenizer_config.json 将 extra_special_tokens 设为 list，
        # 而 transformers<=4.57 的 _set_model_specific_special_tokens 期望 dict
        self._fix_tokenizer_config(model_source)

        logger.info(f"Loading processor from {model_source}")
        processor = None
        try:
            processor = AutoProcessor.from_pretrained(model_source, trust_remote_code=True)
            logger.info("Loaded AutoProcessor successfully")
        except (ValueError, OSError, TypeError) as e:
            logger.warning(f"AutoProcessor failed: {e}, falling back to AutoTokenizer")
            try:
                processor = AutoTokenizer.from_pretrained(
                    model_source, trust_remote_code=True, use_fast=False,
                )
                logger.info("Loaded AutoTokenizer (slow) successfully")
            except Exception as tokenizer_err:
                logger.warning(f"AutoTokenizer (slow) also failed: {tokenizer_err}, trying fast tokenizer")
                processor = AutoTokenizer.from_pretrained(
                    model_source, trust_remote_code=True,
                )
                logger.info("Loaded AutoTokenizer (fast) successfully")
        self._processor = processor

        # Ensure the processor has a chat_template — gemma-4-e4b from ModelScope
        # may lack one, especially after _fix_tokenizer_config modifies tokenizer_config.json.
        if hasattr(processor, "apply_chat_template"):
            try:
                processor.apply_chat_template([{"role": "user", "content": "test"}], tokenize=False, add_generation_prompt=True)
            except (ValueError, AttributeError):
                logger.info("Processor lacks chat_template — injecting Gemma 4 template")
                if hasattr(processor, "tokenizer"):
                    processor.tokenizer.chat_template = GEMMA4_CHAT_TEMPLATE
                else:
                    processor.chat_template = GEMMA4_CHAT_TEMPLATE

        logger.info(f"Loading model from {model_source}")

        # gemma-4-e4b is a multimodal vision-language model that must be loaded as
        # Gemma4ForConditionalGeneration (not Gemma4ForCausalLM) to process images.
        # Gemma4ForCausalLM is the text-only variant and cannot handle pixel_values.
        from transformers import AutoModelForCausalLM as _AutoModelForCausalLM

        # Try loading as the multimodal model first (gemma-4 architecture);
        # fall back to the generic AutoModelForCausalLM if trust_remote_code doesn't
        # map to Gemma4ForConditionalGeneration.
        model = None
        try:
            from transformers import Gemma4ForConditionalGeneration
            model = Gemma4ForConditionalGeneration.from_pretrained(
                model_source,
                dtype=torch.float16,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            logger.info("Loaded model as Gemma4ForConditionalGeneration")
        except (ImportError, Exception) as e:
            logger.warning(f"Cannot load as Gemma4ForConditionalGeneration: {e}, falling back to AutoModelForCausalLM")
            model = _AutoModelForCausalLM.from_pretrained(
                model_source,
                dtype=torch.float16,
                trust_remote_code=True,
                low_cpu_mem_usage=True,
            )
            logger.info("Loaded model as AutoModelForCausalLM")
        self._model = model
        logger.info("Model loaded successfully, moving to device")
        self._model = self._model.to(self.device)
        self._model.eval()
        self._initialized = True
        logger.info(f"Model {self.model_name} loaded successfully on {self.device} (float16, ~8GB)")

    def get_model_name(self) -> str:
        return self.model_name

    async def evaluate(self, rule_prompt: str, output_format_prompt: str = "",
                       image_base64: str = None, text_content: str = None) -> dict:
        """评价单维度质量。

        返回 {"score": float, "eva_content": str}
        """
        import asyncio

        full_prompt = rule_prompt + "\n" + (output_format_prompt or OUTPUT_FORMAT_PROMPT)

        if image_base64:
            result = await self._evaluate_image(image_base64, full_prompt)
        elif text_content:
            truncated = text_content[:settings.max_text_chars]
            full_text = f"以下是需要评价的文本内容：\n\n{truncated}\n\n{full_prompt}"
            result = await self._evaluate_text_inner(full_text)
        else:
            raise ValueError("Must provide either image_base64 or text_content")

        parsed = self._parse_json_response(result)
        return {
            "score": float(parsed.get("score", 0)),
            "eva_content": str(parsed.get("eva_content", "")),
        }

    async def _evaluate_image(self, image_base64: str, prompt: str) -> str:
        import base64
        from PIL import Image
        import io

        def _eval():
            self._init_model()
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            max_size = getattr(settings, "max_image_size", 384)
            if max(image.size) > max_size:
                image.thumbnail((max_size, max_size), Image.LANCZOS)
                logger.info(f"Resized image to {image.size} for faster inference")

            # Use the processor's __call__ with <image> token in text so it
            # expands soft tokens, computes pixel_values, image_position_ids, etc.
            processor = self._processor
            image_token = getattr(processor, "image_token", "<image>")
            content = f"{image_token}\n{prompt}"
            rendered = self._render_chat_template(
                [{"role": "user", "content": content}]
            )
            inputs = processor(
                text=[rendered],
                images=[image],
                return_tensors="pt",
            )
            return self._generate_from_inputs(inputs)

        return await asyncio.to_thread(_eval)

    async def _evaluate_text_inner(self, full_text: str) -> str:
        import asyncio

        def _eval():
            self._init_model()
            rendered = self._render_chat_template(
                [{"role": "user", "content": full_text}]
            )
            processor = self._processor
            tokenizer = getattr(processor, "tokenizer", processor)
            inputs = tokenizer(rendered, return_tensors="pt")
            return self._generate_from_inputs(inputs)

        return await asyncio.to_thread(_eval)

    def _fix_tokenizer_config(self, model_source: str):
        """修复 gemma-4-e4b 模型 tokenizer_config.json 中 extra_special_tokens 为 list 的兼容性问题。

        transformers<=4.57 的 _set_model_specific_special_tokens 期望 extra_special_tokens 是 dict，
        但 gemma-4-e4b 模型的 tokenizer_config.json 中该字段为 list，导致 AttributeError: 'list' object has
        no attribute 'keys'。此处将其转换为 dict 格式。
        """
        import os

        config_path = os.path.join(model_source, "tokenizer_config.json")
        if not os.path.exists(config_path):
            return

        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        extra_tokens = config.get("extra_special_tokens")
        if isinstance(extra_tokens, list):
            # 将 list 转为 dict: {"token_0": token_0, "token_1": token_1, ...}
            config["extra_special_tokens"] = {
                f"token_{i}": token for i, token in enumerate(extra_tokens)
            }
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            logger.info(f"Fixed extra_special_tokens in {config_path}: list -> dict")

    def _render_chat_template(self, messages: list) -> str:
        """Render messages through the Gemma 4 chat template.

        Tries the processor's built-in apply_chat_template first; falls back
        to our bundled GEMMA4_CHAT_TEMPLATE via Jinja2.
        """
        processor = self._processor

        # Try the processor's own apply_chat_template
        if hasattr(processor, "apply_chat_template"):
            try:
                rendered = processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True,
                )
                return rendered
            except (ValueError, AttributeError):
                pass

        # Fallback: render via Jinja2 with our bundled template
        from jinja2 import Template
        return Template(GEMMA4_CHAT_TEMPLATE).render(
            messages=messages, add_generation_prompt=True,
        )

    def _generate_from_inputs(self, inputs: dict) -> str:
        """Run model.generate() on prepared inputs and decode the output.

        Strips ignored keys, moves tensors to device, decodes only new tokens.
        """
        import torch

        processor = self._processor

        # Strip keys that model.generate() does not accept
        inputs = {k: v for k, v in inputs.items() if k not in self._IGNORED_INPUT_KEYS}

        # Move all tensors to device
        inputs = {k: v.to(self.device) if hasattr(v, "to") else v for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=150,
                do_sample=False,
                use_cache=True,
                repetition_penalty=1.2,
            )

        input_len = inputs["input_ids"].shape[1]
        generated = outputs[0][input_len:]
        return processor.decode(generated, skip_special_tokens=True)

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        """从模型输出中提取 JSON 评分结果。

        模型常见问题：
        (1) eva_content 中包含未转义的换行符，导致 JSON 解析失败
        (2) 将分数写成 "99.99分" 而非数字
        (3) 重复规则描述导致 eva_content 中出现嵌套花括号
        此方法处理这些情况。
        """
        import json
        import re

        logger.debug(f"Raw model output (first 300 chars): {text[:300]}")

        # Pre-process: strip control characters (newlines, tabs) that break JSON
        # inside string values, but preserve structural whitespace between tokens.
        # Replace \n and \r inside likely-string regions with spaces.
        cleaned = re.sub(r'[\x00-\x1f]', ' ', text)

        # 1) ```json ... ``` 代码块
        match = re.search(r'```json\s*(.*?)\s*```', cleaned, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict) and "score" in parsed:
                    return parsed
            except json.JSONDecodeError:
                pass

        # 2) Brace-counting: find the first valid JSON with a numeric "score" key.
        #    Scan from each '{' position, find the matching '}', try to parse.
        start = cleaned.find("{")
        while start != -1:
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = cleaned[start:i + 1]
                        try:
                            parsed = json.loads(candidate)
                            if isinstance(parsed, dict) and "score" in parsed:
                                score = parsed["score"]
                                if isinstance(score, (int, float)):
                                    return parsed
                                # Handle string scores like "99.99分" or "100"
                                if isinstance(score, str):
                                    num_match = re.search(r"[\d.]+", score)
                                    if num_match:
                                        parsed["score"] = float(num_match.group())
                                        return parsed
                        except json.JSONDecodeError:
                            pass
                        break
            start = cleaned.find("{", start + 1)

        # 3) Last resort: regex extract score and eva_content separately
        #    eva_content may span multiple lines in model output
        score_match = re.search(r'"score"\s*:\s*([\d.]+)', cleaned)
        content_match = re.search(r'"eva_content"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
        if score_match:
            return {
                "score": float(score_match.group(1)),
                "eva_content": content_match.group(1) if content_match else "",
            }

        # 4) Try original text as-is
        try:
            return json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"Failed to parse model response as JSON: {text[:200]}")
            return {}