"""Verify group chat only responds on explicit @bot (never on @所有人)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.bot_message_events import (
    content_indicates_mention_all,
    evaluate_message_response,
    has_mention_all,
    is_bot_mentioned,
    should_respond_to_message,
)

ALL_ONLY = [{"key": "@_all", "mentioned_type": "user", "id": {"open_id": "all"}, "name": "所有人"}]
BOT_ONLY = [{"key": "@_user_1", "mentioned_type": "bot", "id": {"open_id": "ou_bot"}, "name": "商机机器人"}]
ALL_AND_BOT = ALL_ONLY + BOT_ONLY


def test_at_all_never_triggers_in_group() -> None:
    assert has_mention_all(ALL_ONLY)
    assert not is_bot_mentioned(ALL_ONLY)
    assert not should_respond_to_message(chat_type="group", mentions=ALL_ONLY)

    content = '{"text":"@_all 各位早上好"}'
    assert content_indicates_mention_all(content)
    assert not should_respond_to_message(
        chat_type="group",
        mentions=None,
        content_raw=content,
    )

    decision = evaluate_message_response(chat_type="group", mentions=ALL_ONLY)
    assert decision.reason == "skip_mention_all"


def test_at_all_blocks_even_with_explicit_bot_mention() -> None:
    """大群 @所有人 时飞书可能同时带上 bot mention，仍不回复。"""
    assert is_bot_mentioned(ALL_AND_BOT)
    assert not should_respond_to_message(chat_type="group", mentions=ALL_AND_BOT)


def test_explicit_bot_mention_works() -> None:
    assert should_respond_to_message(chat_type="group", mentions=BOT_ONLY)
    decision = evaluate_message_response(chat_type="group", mentions=BOT_ONLY)
    assert decision.reason == "explicit_bot_mention"


def test_plain_group_chat_ignored() -> None:
    assert not should_respond_to_message(chat_type="group", mentions=None)
    assert not should_respond_to_message(chat_type="group", mentions=[])
    decision = evaluate_message_response(chat_type="group", mentions=[])
    assert decision.reason == "skip_no_bot_mention"


def test_text_mention_robot_without_feishu_mention_ignored() -> None:
    content = '{"text":"可以通过@ 机器人 并提出问题"}'
    assert not should_respond_to_message(
        chat_type="group",
        mentions=None,
        content_raw=content,
    )


def test_p2p_always_responds() -> None:
    assert should_respond_to_message(chat_type="p2p", mentions=None)
    assert should_respond_to_message(chat_type="p2p", mentions=ALL_ONLY)


def main() -> None:
    test_at_all_never_triggers_in_group()
    test_at_all_blocks_even_with_explicit_bot_mention()
    test_explicit_bot_mention_works()
    test_plain_group_chat_ignored()
    test_text_mention_robot_without_feishu_mention_ignored()
    test_p2p_always_responds()
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
