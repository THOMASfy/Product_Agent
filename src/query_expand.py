"""检索词扩展：领域词别名，供 BM25 查询与过滤使用。"""

from __future__ import annotations

# 用户问法 -> 额外匹配词（小写/原文均可，检索时会 lower）
DOMAIN_EXPANSIONS: dict[str, list[str]] = {
    "AI": [
        "AI",
        "ai",
        "人工智能",
        "智能体",
        "智能體",
        "大模型",
        "aigc",
        "AIGC",
        "生成式",
        "生成式人工智能",
        "生成式人工智慧",
        "机器学习",
        "機器學習",
        "深度学习",
        "深度學習",
        "llm",
        "LLM",
        "chatgpt",
        "ChatGPT",
        "artificial intelligence",
        "machine learning",
        "deep learning",
    ],
    "科技": [
        "科技",
        "tech",
        "ai",
        "人工智能",
        "科创",
        "科創",
        "电子",
        "電子",
        "通信",
        "通訊",
        "电脑",
        "電腦",
        "信息技术",
        "信息技術",
        "information technology",
        "物联网",
        "數據",
        "数据",
        "数据中心",
        "算力",
        "cloud",
        "软件",
        "軟件",
        "leap east",
        "数码",
        "數碼",
    ],
    "养老": ["养老", "養老", "长者", "長者", "老龄", "老齡", "健康", "醫療", "医疗", "银发", "銀髮", "大健康"],
    "教育": ["教育", "书展", "書展", "人才", "学术", "學術", "培训", "培訓"],
    "展会": ["展会", "展會", "博览", "博覽", "展览", "展覽", "exhibition", "summit", "峰会", "峰會"],
    "香港": ["香港", "hong kong", "hk", "湾仔", "灣仔"],
    "HKTDC": [
        "HKTDC",
        "hktdc",
        "香港贸易发展局",
        "香港貿易發展局",
        "贸易发展局",
        "貿易發展局",
        "贸发局",
        "貿發局",
        "Hong Kong Trade Development Council",
    ],
    "民生": ["民生", "housing", "welfare", "医疗", "养老", "社区", "惠民", "公共服务", "livelihood"],
    "出海": [
        "出海",
        "走出去",
        "国际化",
        "出口",
        "overseas",
        "go global",
        "export",
        "belt and road",
        "一带一路",
        "globalisation",
        "globalization",
    ],
    "中小企业": [
        "中小企业",
        "中小企",
        "小微",
        "sme",
        "small business",
        "small and medium",
        "entrepreneur",
        "创业",
    ],
    "央企国企": [
        "央企",
        "国企",
        "国有",
        "国资委",
        "state-owned",
        "state owned",
        "soe",
        "central enterprise",
    ],
    "大湾区": [
        "大湾区",
        "大灣區",
        "粤港澳",
        "粵港澳",
        "gba",
        "广州",
        "廣州",
        "深圳",
        "珠海",
        "东莞",
        "東莞",
        "香港",
        "hong kong",
        "hk",
        "澳门",
        "澳門",
        "macau",
        "湾仔",
        "灣仔",
    ],
}


def expand_query_tokens(tokens: list[str], *, raw_query: str = "") -> list[str]:
    """仅当用户明确提到某领域词（整词/整句）时才扩展，避免「香港城市大学」误触发「香港」扩展。"""
    expanded: list[str] = list(tokens)
    normalized_query = raw_query.strip().lower()

    token_set = {t.lower() for t in tokens}
    for key, aliases in DOMAIN_EXPANSIONS.items():
        key_lower = key.lower()
        alias_set = {key_lower, *(a.lower() for a in aliases)}
        if normalized_query == key_lower or token_set.intersection(alias_set):
            expanded.extend([key, *aliases])

    seen: set[str] = set()
    result: list[str] = []
    for item in expanded:
        norm = item.lower()
        if norm in seen:
            continue
        seen.add(norm)
        result.append(item)
    return result
