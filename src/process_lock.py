"""单实例进程锁：避免多个 serve/ws 同时连飞书长连接。"""

from __future__ import annotations

import atexit
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_LOCK_PATH = Path("data/feishu-robot.pid")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_process_lock(*, lock_path: Path | None = None, command: str = "serve") -> None:
    """若已有存活进程持有锁，则退出并提示。"""
    path = lock_path or DEFAULT_LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    current = os.getpid()

    if path.exists():
        try:
            holder = int(path.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            holder = 0
        if holder and holder != current and _pid_alive(holder):
            raise SystemExit(
                f"已有 feishu-robot {command} 进程在运行 (PID {holder})。\n"
                f"请先结束旧进程再启动，避免飞书长连接冲突与旧代码残留。\n"
                f"Windows: taskkill /PID {holder} /F"
            )

    path.write_text(str(current), encoding="utf-8")

    def _release() -> None:
        try:
            if path.exists() and path.read_text(encoding="utf-8").strip() == str(current):
                path.unlink()
        except OSError:
            pass

    atexit.register(_release)
