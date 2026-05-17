import json
import re
import logging

logger = logging.getLogger(__name__)

class SuperParser:
    """
    Standalone module for extracting and standardizing JSON evaluation results
    from raw LLM output.
    """

    @staticmethod
    def parse_json_response(text: str) -> dict:
        """
        超级增强版 2.0.2：
        1. 采用栈式括号匹配提取所有顶级 JSON 对象。
        2. 针对“复读 Prompt”的情况进行过滤。
        3. 优先寻找命中维度关键词 (accuracy, uniqueness等) 的结构。
        """
        if not text:
            return {}

        logger.debug(f"Raw model output (first 300 chars): {text[:300]}")

        # 1. 基础清洗
        cleaned = text
        for ch in ['“', '”', '「', '」', '＂', '『', '』']:
            cleaned = cleaned.replace(ch, '"')
        for ch in ['‘', '’', '′']:
            cleaned = cleaned.replace(ch, "'")
        cleaned = cleaned.replace('：', ':').replace('，', ',')
        cleaned = re.sub(r'[\x00-\x1f]', ' ', cleaned)

        # 2. 括号匹配提取
        potential_objects = []

        def extract_json_structures(s):
            results = []
            # 寻找所有的 { 和 [ 开启点
            starts = [i for i, c in enumerate(s) if c in '{[']
            for start in starts:
                opening = s[start]
                closing = '}' if opening == '{' else ']'
                depth = 0
                for i in range(start, len(s)):
                    if s[i] == opening:
                        depth += 1
                    elif s[i] == closing:
                        depth -= 1
                        if depth == 0:
                            content = s[start:i+1]
                            try:
                                obj = json.loads(content)
                                results.append(obj)
                                # 找到一个后不再深入其内部寻找 start，但可以继续寻找并列的 start
                                break
                            except:
                                pass
            return results

        match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned, re.DOTALL)
        if match:
            potential_objects = extract_json_structures(match.group(1))

        if not potential_objects:
            potential_objects = extract_json_structures(cleaned)

        # 3. 标准化逻辑
        final_result = {}

        # 维度关键词
        DIM_KEYS = ("accuracy", "uniqueness", "consistency", "noinfo", "noise", "completeness", "temporal", "visual", "format", "content")

        def normalize_val(v):
            if isinstance(v, (int, float)):
                return {"score": float(v), "eva_content": ""}
            if isinstance(v, dict):
                res = {"score": -1.0, "eva_content": ""}
                for k, sub_v in v.items():
                    kl = k.lower()
                    if kl == "score":
                        try: res["score"] = float(sub_v)
                        except: pass
                    elif kl in ("eva_content", "evacontent", "description", "eva"):
                        res["eva_content"] = str(sub_v)

                # 处理嵌套
                if res["score"] < 0 and len(v) == 1:
                    inner_v = list(v.values())[0]
                    if isinstance(inner_v, dict):
                        return normalize_val(inner_v)

                if res["score"] < 0: res["score"] = 0.0
                return res
            return {"score": 0.0, "eva_content": str(v)}

        # 4. 合并与过滤
        for obj in potential_objects:
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        # 处理 [{"name": "xxx", "value": 90}]
                        name = str(item.get("name", item.get("Name", "unknown"))).lower()
                        val = item.get("value", item.get("Value", item))
                        # 过滤掉复读 prompt 的 item (如果 score 为 0 且 description 很长)
                        norm = normalize_val(val)
                        if norm["score"] > 0 or len(norm["eva_content"]) < 100:
                            final_result[name] = norm
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    kl = k.lower()
                    # 过滤明显的规则定义项
                    if kl in ("name", "description", "type", "minimum", "maximum", "examplevalue"):
                        continue
                    final_result[kl] = normalize_val(v)

        # 5. 兜底正则
        if not final_result:
            for m in re.finditer(r'"(\w+)":\s*(?:\{[^{}]*)?"score":\s*([\d.]+)', cleaned, re.I):
                final_result[m.group(1).lower()] = {"score": float(m.group(2)), "eva_content": ""}

        # 6. 兼容性总分
        if "score" not in final_result and final_result:
            best_key = next((k for k in final_result if any(dk in k for dk in DIM_KEYS)), list(final_result.keys())[0])
            final_result["score"] = final_result[best_key]

        return final_result
