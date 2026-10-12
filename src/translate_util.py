"""轻量英文→中文翻译（SCMP 简介等）。"""

from __future__ import annotations

import logging
import re
from functools import lru_cache

import requests

logger = logging.getLogger(__name__)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def is_mostly_chinese(text: str, *, threshold: float = 0.2) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    cjk = len(_CJK_RE.findall(stripped))
    return cjk / max(len(stripped), 1) >= threshold


@lru_cache(maxsize=512)
def translate_to_chinese(text: str) -> str:
    """将英文简介译为简体中文；已是中文或失败时返回原文。"""
    stripped = text.strip()
    if not stripped or is_mostly_chinese(stripped):
        return stripped

    try:
        response = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "zh-CN",
                "dt": "t",
                "q": stripped[:5000],
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=15,
        )
        response.raise_for_status()
        chunks = response.json()[0]
        translated = "".join(part[0] for part in chunks if part and part[0])
        return translated.strip() or stripped
    except Exception as exc:
        logger.warning("Translation failed, using original text: %s", exc)
        return stripped
