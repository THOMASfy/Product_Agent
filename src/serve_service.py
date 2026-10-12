"""定时推送 + @机器人 长连接：单进程合并运行。"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

import lark_oapi as lark

from .cache_service import start_auto_cache_refresh
from .feishu_client import FeishuClient
from .lark_ws_service import (
    load_schedule_target,
    load_search_config_from_schedule,
    run_ws_client,
)
from .scheduler_service import run_scheduler

logger = logging.getLogger(__name__)


def run_serve(
    *,
    client: FeishuClient,
    config_path: Path,
    schedule_name: str,
    app_id: str,
    app_secret: str,
    log_level: lark.LogLevel | None = None,
) -> None:
    """BlockingScheduler 跑定时推送；后台线程跑 WS；共享一套缓存刷新。"""
    schedule_target = load_schedule_target(config_path, schedule_name)
    cache_message_config = dict(schedule_target.get("message") or {})
    search_config = load_search_config_from_schedule(config_path, schedule_name)

    start_auto_cache_refresh(cache_message_config)
    logger.info(
        "Shared event cache refresh started for schedule=%r (WS + cron push)",
        schedule_name,
    )

    def ws_worker() -> None:
        try:
            run_ws_client(
                app_id=app_id,
                app_secret=app_secret,
                log_level=log_level,
                search_config=search_config,
                feishu_client=client,
                skip_cache_refresh=True,
            )
        except Exception:
            logger.exception("Feishu WS client stopped unexpectedly")

    ws_thread = threading.Thread(
        target=ws_worker,
        name="feishu-ws",
        daemon=True,
    )
    ws_thread.start()
    logger.info(
        "Feishu WS started in background thread (schedule=%r); starting cron scheduler…",
        schedule_name,
    )

    run_scheduler(client, config_path)


def resolve_feishu_app_credentials() -> tuple[str, str]:
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise SystemExit(
            "缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，"
            "请复制 .env.example 为 .env 并填写凭证。"
        )
    return app_id, app_secret
