# services/model/src/core/providers/openvino_gemma.py
import asyncio
import json
import logging
import threading
import os
from .base import BaseEvalProvider
from ..parser import SuperParser
from ...config import settings

logger = logging.getLogger(__name__)

GEMMA4_CHAT_TEMPLATE = (
    "{% for message in messages %}"
    "<start_of_turn>{{ message.role }}\n"
    "{{ message.content }}\n"
    "<end_of_turn>\n"
    "{% endfor %}"
    "{% if add_generation_prompt %}"
    "<start_of_turn>model\n"
    "{% endif %}"
)

class OpenVINOGemmaEvalProvider(BaseEvalProvider):
    """
    OpenVINO optimized Multimodal Evaluation Provider using OpenVINO GenAI.
    Uses VLMPipeline for high-performance inference on CPU.
    """

    _init_lock = threading.Lock()

    def __init__(self, model_name: str = None, device: str = None, cache_dir: str = None):
        self.model_name = model_name or settings.model_name
        self.device = "CPU"
        self.cache_dir = cache_dir or settings.model_cache_dir
        self._pipe = None
        self._tokenizer = None
        self._initialized = False

    def _init_model(self):
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            self._do_init_model()

    def _do_init_model(self):
        if self.cache_dir:
            os.environ["MODELSCOPE_CACHE"] = self.cache_dir

        logger.info(f"Starting to load OpenVINO model with GenAI: {self.model_name}")

        model_source = self.model_name
        # If it's a modelscope ID, check if it's already in cache
        if "/" in self.model_name and not os.path.exists(self.model_name):
            cache_path = os.path.join(self.cache_dir, "models", self.model_name.replace("/", os.sep))
            if os.path.exists(cache_path):
                model_source = cache_path
                logger.info(f"Using cached model from: {model_source}")
            else:
                from modelscope import snapshot_download
                model_source = snapshot_download(self.model_name)
                logger.info(f"Model downloaded to: {model_source}")

        import openvino_genai as ov_genai
        
        logger.info(f"Initializing VLMPipeline on {self.device}")
        # VLMPipeline handles loading of all components
        self._pipe = ov_genai.VLMPipeline(model_source, self.device)
        
        try:
            self._tokenizer = self._pipe.get_tokenizer()
            logger.info("Successfully retrieved tokenizer from VLMPipeline")
        except Exception as e:
            logger.warning(f"Could not get tokenizer from VLMPipeline: {e}")

        self._initialized = True
        logger.info(f"OpenVINO GenAI Model {self.model_name} loaded successfully")

    def get_model_name(self) -> str:
        return self.model_name

    def _render_chat_template(self, prompt: str) -> str:
        """根据模型类型渲染聊天模板。"""
        # 1. 尝试使用 OpenVINO Tokenizer 的 apply_chat_template
        if self._tokenizer and hasattr(self._tokenizer, "apply_chat_template"):
            try:
                messages = [{"role": "user", "content": prompt}]
                # add_generation_prompt=True 确保模型开始生成
                rendered = self._tokenizer.apply_chat_template(messages, add_generation_prompt=True)
                logger.info("Used OpenVINO Tokenizer to apply chat template")
                return rendered
            except Exception as e:
                logger.warning(f"apply_chat_template failed: {e}")

        # 2. 手动回退模板
        model_name_lower = self.model_name.lower()
        if "gemma" in model_name_lower:
            # Gemma 模板
            return f"<start_of_turn>user\n{prompt}<end_of_turn>\n<start_of_turn>model\n"
        elif "qwen" in model_name_lower:
            # Qwen 模板
            return f"<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # 默认不处理
        return prompt

    async def evaluate(self, rule_prompt: str, output_format_prompt: str = "",
                       image_base64: str = None, text_content: str = None,
                       video_frames: list[str] = None) -> dict:
        
        from ..providers.gemma4 import OUTPUT_FORMAT_PROMPT
        full_prompt = rule_prompt + "\n" + (output_format_prompt or OUTPUT_FORMAT_PROMPT)

        if video_frames:
            result = await self._evaluate_video(video_frames, full_prompt)
        elif image_base64:
            result = await self._evaluate_image(image_base64, full_prompt)
        elif text_content:
            truncated = text_content[:settings.max_text_chars]
            full_text = f"以下是需要评价的内容：\n\n{truncated}\n\n{full_prompt}"
            result = await self._evaluate_text_inner(full_text)
        else:
            raise ValueError("Must provide image_base64, text_content, or video_frames")

        # OpenVINO GenAI returns a string (or DecodedResults which has a __str__)
        parsed = SuperParser.parse_json_response(str(result))
        logger.info(f"Parsed JSON result: {parsed}")
        return parsed

    async def _evaluate_image(self, image_base64: str, prompt: str) -> str:
        import base64
        from PIL import Image
        import io
        import numpy as np
        import openvino as ov

        def _eval():
            self._init_model()
            image_bytes = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            
            # Ensure minimum size of 28x28 as required by Qwen2-VL
            w, h = image.size
            if w < 28 or h < 28:
                new_w = max(w, 28)
                new_h = max(h, 28)
                image = image.resize((new_w, new_h), Image.LANCZOS)
                logger.info(f"Resized small image from {w}x{h} to {new_w}x{new_h}")
            
            # Ensure maximum size for performance
            max_size = getattr(settings, "max_image_size", 384)
            if max(image.size) > max_size:
                image.thumbnail((max_size, max_size), Image.LANCZOS)
                logger.info(f"Resized large image to {image.size} for faster inference")

            # Apply chat template
            formatted_prompt = self._render_chat_template(prompt)

            # Convert PIL to OpenVINO Tensor
            image_data = np.array(image)
            ov_tensor = ov.Tensor(image_data)
            
            logger.info(f"Running GenAI inference with formatted prompt: {formatted_prompt[:100]}...")
            # Note: GenAI VLMPipeline generate takes prompt and image(s)
            output = self._pipe.generate(formatted_prompt, image=ov_tensor, max_new_tokens=512, do_sample=False)
            return str(output)

        return await asyncio.to_thread(_eval)

    async def _evaluate_text_inner(self, full_text: str) -> str:
        def _eval():
            self._init_model()
            # Apply chat template
            formatted_prompt = self._render_chat_template(full_text)
            # VLMPipeline handles text-only prompts fine
            output = self._pipe.generate(formatted_prompt, max_new_tokens=512, do_sample=False)
            return str(output)

        return await asyncio.to_thread(_eval)

    async def _evaluate_video(self, video_frames: list[str], prompt: str) -> str:
        import base64
        from PIL import Image
        import io
        import numpy as np
        import openvino as ov

        def _eval():
            self._init_model()
            tensors = []
            max_size = getattr(settings, "max_image_size", 384)
            for b64 in video_frames:
                img_bytes = base64.b64decode(b64)
                img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
                
                # Ensure minimum size
                w, h = img.size
                if w < 28 or h < 28:
                    new_w = max(w, 28)
                    new_h = max(h, 28)
                    img = img.resize((new_w, new_h), Image.LANCZOS)
                
                # Ensure maximum size
                if max(img.size) > max_size:
                    img.thumbnail((max_size, max_size), Image.LANCZOS)
                
                tensors.append(ov.Tensor(np.array(img)))

            # Apply chat template
            formatted_prompt = self._render_chat_template(prompt)

            # VLMPipeline.generate supports a list of images (treated as video frames)
            output = self._pipe.generate(formatted_prompt, images=tensors, max_new_tokens=512, do_sample=False)
            return str(output)

        return await asyncio.to_thread(_eval)
