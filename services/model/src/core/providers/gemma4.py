# services/model/src/core/providers/gemma4.py
import logging
from .base import BaseEvalProvider
from ...config import settings

OUTPUT_FORMAT_PROMPT = """完成之后严格按照以下JSON格式返回结果，不要返回其他任何内容：{"score": 0.00, "eva_content": "..."}，其中score为规则得分(百分制，保留两位小数的数字)，eva_content为相应的评价内容，使用中文描述(字符串)。"""

logger = logging.getLogger(__name__)


class Gemma4EvalProvider(BaseEvalProvider):
    """使用 gemma-4-e4b 模型进行数据质量评价。

    模型通过 ModelScope 下载，支持 CPU / GPU / NPU。
    CPU 模式下使用 float32 精度保证兼容性。
    """

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

        from transformers import AutoProcessor, Gemma3ForConditionalGeneration
        import torch

        torch_dtype = torch.float32 if self.device == "cpu" else torch.float16

        logger.info(f"Loading processor from {model_source}")
        self._processor = AutoProcessor.from_pretrained(model_source)

        logger.info(f"Loading model from {model_source}, dtype={torch_dtype}")
        self._model = Gemma3ForConditionalGeneration.from_pretrained(
            model_source,
            torch_dtype=torch_dtype,
        ).to(self.device)
        self._model.eval()
        self._initialized = True
        logger.info(f"Model {self.model_name} loaded successfully on {self.device}")

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

    def _run_inference(self, messages: list) -> str:
        import torch

        inputs = self._processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        input_len = inputs["input_ids"].shape[1]
        generated = outputs[0][input_len:]
        return self._processor.decode(generated, skip_special_tokens=True)

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