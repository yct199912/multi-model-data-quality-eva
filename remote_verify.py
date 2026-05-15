import asyncio
import os
import sys

# Add src to path
sys.path.append(os.path.join(os.getcwd(), "services/model/src"))

from core.providers.gemma4 import Gemma4EvalProvider
from config import settings

async def test_combined_eval():
    provider = Gemma4EvalProvider()
    # Mocking the model loading if needed, or just let it try to load
    # Since we want to test the full flow, we'll let it init.
    # We'll use a very short text to minimize time.
    rule_prompt = "请进行综合评价。"
    text_content = "这是一个测试文本。它描述了一个阳光明媚的早晨。"
    
    print("Initializing model (this may take time)...")
    # Note: This will download the model if not present.
    # The remote machine should have it in /models or similar.
    
    try:
        # We can't easily run the full model in a quick script if it's 8GB, 
        # but we can at least test the parsing and flow.
        # Let's mock the _generate_from_inputs to return a combined JSON.
        
        provider._initialized = True
        provider.device = "cpu"
        
        # Test parsing first with a complex string
        complex_text = """
        分析结果：
        {
          "accuracy": {"score": 88, "eva_content": "准确"},
          "noinfo": {"score": 90, "eva_content": "清晰"},
          "noise": {"score": 85, "eva_content": "无噪声"},
          "uniqueness": {"score": 70, "eva_content": "还可以"},
          "consistency": {"score": 92, "eva_content": "一致"}
        }
        """
        parsed = provider._parse_json_response(complex_text)
        print(f"Parsed combined JSON: {parsed}")
        assert parsed["accuracy"]["score"] == 88
        
        print("Test passed!")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_combined_eval())
