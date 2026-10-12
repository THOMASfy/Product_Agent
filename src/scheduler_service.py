"""加载定时任务配置并执行群发。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .feishu_client import FeishuAPIError, FeishuClient
from .message_builder import build_content, build_events_content

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = ZoneInfo("Asia/Shanghai")


def load_schedules(config_path: Path) -> list[dict[str, Any]]:
    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("schedules", [])


def _validate_chat_id(chat_id: str) -> None:
    if "xxxx" in chat_id.lower():
        raise ValueError(
            f"chat_id 仍是占位符（{chat_id}），请在 config/schedules.yaml 中填写真实群 chat_id"
        )


def send_scheduled_message(
    client: FeishuClient,
    schedule_name: str,
    chat_ids: list[str],
    message: dict[str, Any],
) -> bool:
    logger.info("[%s] triggered", schedule_name)

    for chat_id in chat_ids:
        _validate_chat_id(chat_id)

    try:
        logger.info("[%s] building message content", schedule_name)
        if message.get("type") == "events":
            built = build_events_content(message, skip_if_empty=True)
            if built is None:
                logger.info(
                    "[%s] no events to push today (empty after filter), skip send",
                    schedule_name,
                )
                return True
            msg_type, content = built
        else:
            msg_type, content = build_content(message)
        logger.info("[%s] message content built successfully, type=%s", schedule_name, msg_type)
    except Exception:
        logger.exception("[%s] failed while building message content", schedule_name)
        return False

    all_ok = True
    for chat_id in chat_ids:
        try:
            logger.info("[%s] sending message to chat %s", schedule_name, chat_id)
            result = client.send_message_to_chat(chat_id, msg_type, content)
            message_id = result.get("message_id", "unknown")
            logger.info(
                "[%s] sent to chat %s, message_id=%s",
                schedule_name,
                chat_id,
                message_id,
            )
        except FeishuAPIError as exc:
            all_ok = False
            logger.error(
                "[%s] failed to send to chat %s: Feishu error %s: %s (log_id=%s)",
                schedule_name,
                chat_id,
                exc.code,
                exc.msg,
                exc.log_id,
            )
        except Exception:
            all_ok = False
            logger.exception("[%s] failed to send to chat %s", schedule_name, chat_id)
    logger.info("[%s] finished, success=%s", schedule_name, all_ok)
    return all_ok


def parse_cron(cron_expr: str) -> dict[str, str]:
    """解析 '分 时 日 月 周' 五段 cron 表达式。"""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"无效的 cron 表达式（需要 5 段）: {cron_expr}")

    minute, hour, day, month, day_of_week = parts
    return {
        "minute": minute,
        "hour": hour,
        "day": day,
        "month": month,
        "day_of_week": day_of_week,
    }


def run_scheduler(client: FeishuClient, config_path: Path) -> None:
    schedules = load_schedules(config_path)
    scheduler = BlockingScheduler(timezone=DEFAULT_TIMEZONE)

    enabled_count = 0
    for item in schedules:
        if not item.get("enabled", True):
            logger.info("Skip disabled schedule: %s", item.get("name"))
            continue

        name = item["name"]
        cron = parse_cron(item["cron"])
        chat_ids = item["chat_ids"]
        message = item["message"]
        msg_type = message.get("type", "text")
        logger.info(
            "Registered schedule '%s' cron=%s type=%s chats=%s timezone=%s",
            name,
            item["cron"],
            msg_type,
            chat_ids,
            DEFAULT_TIMEZONE,
        )

        trigger = CronTrigger(**cron, timezone=DEFAULT_TIMEZONE)
        scheduler.add_job(
            send_scheduled_message,
            trigger=trigger,
            kwargs={
                "client": client,
                "schedule_name": name,
                "chat_ids": chat_ids,
                "message": message,
            },
            id=name,
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )
        next_run = getattr(scheduler.get_job(name), "next_run_time", None)
        if next_run is None:
            next_run = trigger.get_next_fire_time(None, datetime.now(DEFAULT_TIMEZONE))
        if next_run is not None:
            logger.info(
                "Schedule '%s' next push at %s",
                name,
                next_run.astimezone(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z"),
            )
        enabled_count += 1

    if enabled_count == 0:
        raise RuntimeError("没有启用的定时任务，请检查 config/schedules.yaml")

    now = datetime.now(DEFAULT_TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z")
    logger.info(
        "Scheduler started with %d job(s) at %s. Press Ctrl+C to stop.",
        enabled_count,
        now,
    )
    scheduler.start()
