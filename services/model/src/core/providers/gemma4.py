# services/model/src/core/providers/gemma4.py
import asyncio
import json
import logging
import threading
from .base import BaseEvalProvider
from ...config import settings

OUTPUT_FORMAT_PROMPT = """完成之后严格按照以下JSON格式返回结果，不要返回其他任何内容：{"score": 0.00, "eva_content": "..."}，其中score为规则得分(百分制，保留两位小数的数字)，eva_content为相应的评价内容，使用中文描述(字符串)。"""

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
        self._model = AutoModelForCausalLM.from_pretrained(
            model_source,
            dtype=torch.float16,
            trust_remote_code=True,
            low_cpu_mem_usage=True,
        )
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
            messages = [
                {"role": "user", "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ]}
            ]
            return self._run_inference(messages)

        return await asyncio.to_thread(_eval)

    async def _evaluate_text_inner(self, full_text: str) -> str:
        import asyncio

        def _eval():
            self._init_model()
            messages = [
                {"role": "user", "content": [
                    {"type": "text", "text": full_text},
                ]}
            ]
            return self._run_inference(messages)

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

    def _run_inference(self, messages: list) -> str:
        import torch

        processor = self._processor

        if hasattr(processor, "apply_chat_template"):
            try:
                inputs = processor.apply_chat_template(
                    messages,
                    tokenize=True,
                    add_generation_prompt=True,
                    return_dict=True,
                    return_tensors="pt",
                ).to(self.device)
            except (ValueError, AttributeError):
                inputs = self._apply_manual_chat_template(messages)
        else:
            inputs = self._apply_manual_chat_template(messages)

        # Strip keys that image_processor adds but model.generate() rejects
        inputs = {k: v for k, v in inputs.items() if k not in self._IGNORED_INPUT_KEYS}

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        input_len = inputs["input_ids"].shape[1]
        generated = outputs[0][input_len:]
        return processor.decode(generated, skip_special_tokens=True)

    # Keys produced by image_processor that model.generate() does not accept
    _IGNORED_INPUT_KEYS = {"num_soft_tokens_per_image"}

    def _apply_manual_chat_template(self, messages: list) -> dict:
        """Manually apply Gemma 4 chat template when the processor lacks one.

        Renders the Jinja2 template to text, then tokenizes and prepares
        pixel_values / attention_mask tensors for the model.
        """
        import torch

        template_str = GEMMA4_CHAT_TEMPLATE

        # Extract images and build text-only messages for template rendering
        images = []
        text_messages = []
        for msg in messages:
            content = msg.get("content", [])
            if isinstance(content, str):
                text_messages.append(msg)
                continue
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "image":
                            images.append(part["image"])
                            text_parts.append({"type": "text", "text": ""})
                        elif part.get("type") == "text":
                            text_parts.append(part)
                text_messages.append({"role": msg["role"], "content": text_parts if len(text_parts) > 1 else text_parts[0] if text_parts else ""})

        from jinja2 import Template
        template = Template(template_str)
        rendered = template.render(messages=text_messages, add_generation_prompt=True)

        # Get the tokenizer — either from a Processor object or standalone
        tokenizer = getattr(self._processor, "tokenizer", self._processor)

        if images and hasattr(self._processor, "image_processor"):
            text_inputs = tokenizer(rendered, return_tensors="pt", add_special_tokens=False)
            image_inputs = self._processor.image_processor(images=images, return_tensors="pt")
            # Merge dicts, stripping keys the model doesn't accept
            inputs = {}
            for k, v in text_inputs.items():
                if k not in self._IGNORED_INPUT_KEYS:
                    inputs[k] = v.to(self.device)
            for k, v in image_inputs.items():
                if k not in self._IGNORED_INPUT_KEYS:
                    inputs[k] = v.to(self.device)
        else:
            inputs = tokenizer(rendered, return_tensors="pt")
            inputs = {k: v.to(self.device) for k, v in inputs.items()}

        return inputs

    @staticmethod
    def _parse_json_response(text: str) -> dict:
        import json
        import re
        try:
            match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            match = re.search(r"\{[^}]+\}", text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
            return json.loads(text)
        except (json.JSONDecodeError, AttributeError):
            logger.warning(f"Failed to parse model response as JSON: {text[:200]}")
            return {}