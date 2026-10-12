"""飞书定时群发 + @机器人 检索回复入口。"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

from src.feishu_client import FeishuClient
from src.scheduler_service import run_scheduler, send_scheduled_message

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config" / "schedules.yaml"


def _cleanup_stale_logs(log_dir: Path, *, pattern: str, max_age_days: int) -> int:
    """删除超过保留天数的旧日志文件（含轮转备份）。"""
    if max_age_days <= 0:
        return 0
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for path in log_dir.glob(pattern):
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)

    max_bytes = max(1, int(os.getenv("LOG_MAX_MB", "2"))) * 1_000_000
    backup_count = max(1, int(os.getenv("LOG_BACKUP_COUNT", "5")))
    retention_days = max(0, int(os.getenv("LOG_RETENTION_DAYS", "30")))

    removed = _cleanup_stale_logs(log_dir, pattern="feishu-robot.log*", max_age_days=retention_days)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(
                log_dir / "feishu-robot.log",
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            ),
        ],
    )
    logging.getLogger(__name__).info(
        "Logging: file=%s, rotate=%sMB x %s backups, retention=%s days (removed %s stale files)",
        log_dir / "feishu-robot.log",
        max_bytes // 1_000_000,
        backup_count,
        retention_days,
        removed,
    )


def create_client() -> FeishuClient:
    app_id = os.getenv("FEISHU_APP_ID")
    app_secret = os.getenv("FEISHU_APP_SECRET")
    base_url = os.getenv("FEISHU_BASE_URL")

    if not app_id or not app_secret:
        raise SystemExit(
            "缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，"
            "请复制 .env.example 为 .env 并填写凭证。"
        )

    return FeishuClient(app_id=app_id, app_secret=app_secret, base_url=base_url)


def cmd_run_once(client: FeishuClient, config_path: Path, schedule_name: str) -> None:
    from src.scheduler_service import load_schedules

    schedules = load_schedules(config_path)
    target = next((s for s in schedules if s.get("name") == schedule_name), None)
    if not target:
        raise SystemExit(f"未找到名为 '{schedule_name}' 的任务")

    ok = send_scheduled_message(
        client=client,
        schedule_name=schedule_name,
        chat_ids=target["chat_ids"],
        message=target["message"],
    )
    if not ok:
        raise SystemExit(
            f"任务 '{schedule_name}' 抓取完成，但消息发送失败。"
            "请检查 config/schedules.yaml 中的 chat_id、机器人是否已入群、应用权限是否已开通。"
        )
    print(f"任务 '{schedule_name}' 已手动执行一次")


def cmd_refresh_cache(config_path: Path, schedule_name: str) -> None:
    from src.cache_service import refresh_event_cache
    from src.scheduler_service import load_schedules

    schedules = load_schedules(config_path)
    target = next((s for s in schedules if s.get("name") == schedule_name), None)
    if not target:
        raise SystemExit(f"未找到名为 '{schedule_name}' 的任务")

    stats = refresh_event_cache(target["message"])
    print(
        f"缓存已刷新：抓取 {stats['fetched']} 条，写入 {stats['upserted']} 条，"
        f"向量 {stats.get('embedded', 0)} 条，"
        f"清理 {stats['removed']} 条，当前共 {stats['total']} 条。"
    )


def main() -> None:
    load_dotenv(ROOT / ".env")

    parser = argparse.ArgumentParser(description="飞书定时群发 + @机器人 检索")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="启动定时推送调度服务")
    run_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="定时任务配置文件路径",
    )

    once_parser = sub.add_parser("run-once", help="立即执行一次定时推送任务")
    once_parser.add_argument("--name", required=True, help="schedules.yaml 中的 name")
    once_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="定时任务配置文件路径",
    )

    refresh_parser = sub.add_parser("refresh-cache", help="抓取活动并写入本地 SQLite 缓存")
    refresh_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="定时任务配置文件路径",
    )
    refresh_parser.add_argument("--name", default="weekly-hk-events", help="schedules.yaml 中的任务名")

    serve_parser = sub.add_parser(
        "serve",
        help="单进程：定时推送 + @机器人 长连接（推荐生产环境）",
    )
    serve_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="定时任务配置文件路径",
    )
    serve_parser.add_argument(
        "--schedule-name",
        default=os.getenv("SEARCH_SCHEDULE_NAME", "weekly-hk-events"),
        help="@检索与缓存刷新使用的任务名",
    )
    serve_parser.add_argument(
        "--debug-sdk",
        action="store_true",
        help="输出 lark-oapi SDK 调试日志",
    )

    ws_parser = sub.add_parser("ws", help="仅启动长连接（@机器人 检索回复）")
    ws_parser.add_argument(
        "--debug-sdk",
        action="store_true",
        help="输出 lark-oapi SDK 调试日志",
    )
    ws_parser.add_argument(
        "--config",
        default=str(DEFAULT_CONFIG),
        help="检索时使用的 schedules.yaml 路径",
    )
    ws_parser.add_argument(
        "--schedule-name",
        default=os.getenv("SEARCH_SCHEDULE_NAME", "weekly-hk-events"),
        help="检索时使用的任务名",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "refresh-cache":
        cmd_refresh_cache(Path(args.config), args.name)
        return

    if args.command == "serve":
        import lark_oapi as lark

        from src.process_lock import acquire_process_lock
        from src.serve_service import resolve_feishu_app_credentials, run_serve

        acquire_process_lock(command="serve")

        app_id, app_secret = resolve_feishu_app_credentials()
        level = lark.LogLevel.DEBUG if args.debug_sdk or args.verbose else lark.LogLevel.INFO
        run_serve(
            client=create_client(),
            config_path=Path(args.config),
            schedule_name=args.schedule_name,
            app_id=app_id,
            app_secret=app_secret,
            log_level=level,
        )
        return

    if args.command == "ws":
        logging.getLogger(__name__).warning(
            "main.py ws 仅 @机器人 长连接，不含定时推送；生产环境请用: python main.py serve"
        )
        import lark_oapi as lark

        from src.process_lock import acquire_process_lock
        from src.lark_ws_service import (
            load_schedule_target,
            load_search_config_from_schedule,
            run_ws_client,
        )
        from src.serve_service import resolve_feishu_app_credentials

        acquire_process_lock(command="ws")
        app_id, app_secret = resolve_feishu_app_credentials()

        level = lark.LogLevel.DEBUG if args.debug_sdk or args.verbose else lark.LogLevel.INFO
        schedule_target = load_schedule_target(Path(args.config), args.schedule_name)
        cache_message_config = dict(schedule_target.get("message") or {})
        search_config = load_search_config_from_schedule(
            Path(args.config),
            args.schedule_name,
        )
        run_ws_client(
            app_id=app_id,
            app_secret=app_secret,
            log_level=level,
            search_config=search_config,
            cache_message_config=cache_message_config,
            feishu_client=create_client(),
        )
        return

    client = create_client()
    if args.command == "run":
        run_scheduler(client, Path(args.config))
    elif args.command == "run-once":
        cmd_run_once(client, Path(args.config), args.name)


if __name__ == "__main__":
    main()
