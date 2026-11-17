"""诊断日志：出问题时能拿出来看"到底卡在哪"。

写到 data/diag.log，超过 2MB 自动滚一份 diag.log.1。
界面上「导入数据」页有按钮可以直接打开这个目录。
"""

from __future__ import annotations

import os
import platform
import sys
import threading
import time
import traceback
from pathlib import Path

MAX_BYTES = 2_000_000
_lock = threading.Lock()
_log_path: Path | None = None


def set_dir(path: Path) -> None:
    global _log_path
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        _log_path = Path(path) / "diag.log"
    except OSError:
        _log_path = None


def log_path() -> Path | None:
    return _log_path


def _rotate(p: Path) -> None:
    try:
        if p.exists() and p.stat().st_size > MAX_BYTES:
            backup = p.with_suffix(".log.1")
            if backup.exists():
                backup.unlink()
            p.rename(backup)
    except OSError:
        pass


def log(msg: str, level: str = "INFO") -> None:
    """写一行诊断日志。永远不抛异常，日志失败不能把主流程带崩。"""
    p = _log_path
    if p is None:
        return
    line = "%s [%-5s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, msg)
    try:
        with _lock:
            _rotate(p)
            with open(p, "a", encoding="utf-8", errors="ignore") as fh:
                fh.write(line)
    except OSError:
        pass


def info(msg: str) -> None:
    log(msg, "INFO")


def warn(msg: str) -> None:
    log(msg, "WARN")


def error(msg: str) -> None:
    log(msg, "ERROR")


def exception(msg: str) -> None:
    log(msg + "\n" + traceback.format_exc(), "ERROR")


def dump_env() -> None:
    """启动时写一段环境信息，排查"他的机器上为什么不行"最有用。"""
    try:
        info("=" * 60)
        info("RiftStats 启动")
        info("时间       : %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
        info("Python     : %s" % sys.version.replace("\n", " "))
        info("平台       : %s %s" % (platform.system(), platform.release()))
        info("冻结运行   : %s" % bool(getattr(sys, "frozen", False)))
        info("可执行文件 : %s" % sys.executable)
        info("工作目录   : %s" % os.getcwd())
        info("日志文件   : %s" % _log_path)
        from .store import data_dir

        info("数据目录   : %s" % data_dir())
        info("区域设置   : %s" % os.environ.get("LANG", ""))
    except Exception:
        pass


def dump_client(client, paths: list[str] | None = None) -> None:
    """把客户端几个关键接口挨个打一遍，记录状态码/耗时/响应片段。"""
    if client is None:
        warn("dump_client: 客户端对象为空")
        return
    info("客户端端口 : %s" % getattr(client.lock, "port", "?"))
    probe = paths or [
        "/lol-summoner/v1/current-summoner",
        "/lol-gameflow/v1/gameflow-phase",
        "/lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=1",
    ]
    for path in probe:
        started = time.time()
        try:
            data = client.get(path, timeout=6.0)
            cost = (time.time() - started) * 1000
            text = str(data)
            info("  GET %-70s 200  %5.0fms  %s" % (path[:70], cost, text[:120]))
        except Exception as exc:
            cost = (time.time() - started) * 1000
            body = ""
            resp = getattr(exc, "read", None)
            if callable(resp):
                try:
                    body = exc.read().decode("utf-8", "ignore")[:200]
                except Exception:
                    body = ""
            error(
                "  GET %-70s 失败 %5.0fms  %s: %s %s"
                % (path[:70], cost, type(exc).__name__, exc, body)
            )
