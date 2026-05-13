# services/model/src/core/providers/base.py
from abc import ABC, abstractmethod


class BaseEvalProvider(ABC):
    """模型质量评价服务抽象基类。"""

    @abstractmethod
    async def evaluate(self, rule_prompt: str, output_format_prompt: str,
                       image_base64: str = None, text_content: str = None) -> dict:
        """评价单维度质量。

        Args:
            rule_prompt: 规则提示词（从 eval_prompts 获取）
            output_format_prompt: 输出格式提示词
            image_base64: Base64 编码的图像数据（图像评价时提供）
            text_content: 文本内容（文本评价时提供）

        Returns:
            {"score": float, "eva_content": str}
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """返回模型名称。"""
        pass