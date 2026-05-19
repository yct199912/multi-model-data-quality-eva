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
        超级增强版 3.0:
        1. 采用栈式括号匹配提取所有顶级 JSON 对象。
        2. 智能识别单维度 vs 多维度输出:
           - 单维度: {"score": 95.76, "eva_content": "..."} -> 直接提取
           - 多维度: {"accuracy": {"score": 76, ...}, ...} -> 按维度标准化
        3. 针对"复读 Prompt"的情况进行过滤。
        4. 优先寻找命中维度关键词 (accuracy, uniqueness等) 的结构。
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
                                break
                            except Exception:
                                pass
            return results

        match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned, re.DOTALL)
        if match:
            potential_objects = extract_json_structures(match.group(1))

        if not potential_objects:
            potential_objects = extract_json_structures(cleaned)

        # 维度关键词
        DIM_KEYS = ("accuracy", "uniqueness", "consistency", "noinfo", "noise",
                     "completeness", "temporal", "visual", "format", "content",
                     "integrity", "effective")

        def normalize_val(v):
            """将任意值标准化为 {"score": float, "eva_content": str} 结构。"""
            if isinstance(v, (int, float)):
                return {"score": float(v), "eva_content": ""}
            if isinstance(v, dict):
                res = {"score": -1.0, "eva_content": ""}
                for k, sub_v in v.items():
                    kl = k.lower()
                    if kl == "score":
                        try:
                            res["score"] = float(sub_v)
                        except (ValueError, TypeError):
                            pass
                    elif kl in ("eva_content", "evacontent", "description", "eva"):
                        res["eva_content"] = str(sub_v)
                # 处理嵌套 dict (值本身是 {"score": ..., "eva_content": ...})
                if res["score"] < 0 and len(v) == 1:
                    inner_v = list(v.values())[0]
                    if isinstance(inner_v, dict):
                        return normalize_val(inner_v)
                if res["score"] < 0:
                    res["score"] = 0.0
                return res
            return {"score": 0.0, "eva_content": str(v)}

        def is_flat_score_dict(obj: dict) -> bool:
            """判断是否是单维度平铺格式, 如 {"score": 95.76, "eva_content": "..."}。
            特征: 包含 score 键且值为数字, 或包含 eva_content 且值为字符串。
            """
            has_numeric_score = any(
                k.lower() == "score" and isinstance(v, (int, float))
                for k, v in obj.items()
            )
            has_string_eva = any(
                k.lower() in ("eva_content", "evacontent", "description", "eva")
                and isinstance(v, str)
                for k, v in obj.items()
            )
            return has_numeric_score or has_string_eva

        # 3. 解析提取到的 JSON 对象
        final_result = {}

        for obj in potential_objects:
            if isinstance(obj, list):
                for item in obj:
                    if isinstance(item, dict):
                        name = str(item.get("name", item.get("Name", "unknown"))).lower()
                        val = item.get("value", item.get("Value", item))
                        norm = normalize_val(val)
                        if norm["score"] > 0 or len(norm["eva_content"]) < 100:
                            final_result[name] = norm
            elif isinstance(obj, dict):
                # 单维度平铺格式: {"score": 95.76, "eva_content": "..."}
                # 直接提取 score 和 eva_content, 不做维度拆分
                if is_flat_score_dict(obj):
                    flat = {}
                    for k, v in obj.items():
                        kl = k.lower()
                        if kl == "score" and isinstance(v, (int, float)):
                            flat["score"] = float(v)
                        elif kl in ("eva_content", "evacontent", "description", "eva") and isinstance(v, str):
                            flat["eva_content"] = v
                    if "score" not in flat:
                        flat["score"] = 0.0
                    if "eva_content" not in flat:
                        flat["eva_content"] = ""
                    # 保留其他维度字段
                    for k, v in obj.items():
                        kl = k.lower()
                        if kl not in ("score", "eva_content", "evacontent", "description", "eva"):
                            final_result[kl] = normalize_val(v)
                    # score/eva_content 不覆盖已有的维度结果
                    if "score" not in final_result:
                        final_result["score"] = flat["score"]
                    if "eva_content" not in final_result:
                        final_result["eva_content"] = flat["eva_content"]
                    continue

                for k, v in obj.items():
                    kl = k.lower()
                    # 过滤明显的规则定义项
                    if kl in ("name", "description", "type", "minimum", "maximum", "examplevalue"):
                        continue
                    final_result[kl] = normalize_val(v)

        # 4. 兜底正则
        if not final_result:
            for m in re.finditer(r'"(\w+)":\s*(?:\{[^{}]*)?"score":\s*([\d.]+)', cleaned, re.I):
                final_result[m.group(1).lower()] = {"score": float(m.group(2)), "eva_content": ""}

        # 5. 兼容性总分
        if "score" not in final_result and final_result:
            best_key = next((k for k in final_result if any(dk in k for dk in DIM_KEYS)), list(final_result.keys())[0])
            final_result["score"] = final_result[best_key]

        return final_result