"""数据源：英雄联盟客户端本地接口（LCU）。

原理：客户端启动后会在安装目录写一个 lockfile，内容是
`LeagueClient:pid:port:password:https`。用 Basic 认证（用户名固定 riot）
访问 https://127.0.0.1:port 就能拿到你自己的全部对战记录，不需要任何
API key，也不需要截图。
"""

from __future__ import annotations

import base64
import glob
import json
import os
import re
import ssl
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .. import diag
from ..models import BLUE, RED, Match, Participant
from ..store import data_dir

# 国服常见布局：<盘>:\League of Legends\英雄联盟\lockfile
# 国际服常见布局：<盘>:\Riot Games\League of Legends\lockfile
DEFAULT_PATHS = [
    r"C:\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    r"E:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\League of Legends\英雄联盟\lockfile",
    r"C:\League of Legends\英雄联盟\lockfile",
    r"E:\League of Legends\英雄联盟\lockfile",
    r"C:\WeGameApps\英雄联盟\lockfile",
    r"D:\WeGameApps\英雄联盟\lockfile",
    r"C:\Program Files (x86)\WeGameApps\英雄联盟\lockfile",
]

# 注册表里记录的安装目录（国服由腾讯的启动器写）
REGISTRY_KEYS = [
    (r"SOFTWARE\Tencent\LOL", "InstallPath", "HKCU"),
    (r"SOFTWARE\WOW6432Node\Tencent\LOL", "InstallPath", "HKLM"),
    (r"SOFTWARE\Riot Games\League of Legends", "InstallLocation", "HKLM"),
    (r"SOFTWARE\WOW6432Node\Riot Games\League of Legends", "InstallLocation", "HKLM"),
]

DRIVE_LETTERS = "CDEFGH"


@dataclass
class Lockfile:
    process: str
    pid: int
    port: int
    password: str
    protocol: str

    @classmethod
    def parse(cls, text: str) -> "Lockfile":
        parts = text.strip().split(":")
        if len(parts) < 5:
            raise ValueError("lockfile 格式不对")
        return cls(parts[0], int(parts[1]), int(parts[2]), parts[3], parts[4])

    def __repr__(self) -> str:  # 日志里别把密码打出来
        return "Lockfile(port=%s, protocol=%s)" % (self.port, self.protocol)

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://127.0.0.1:{self.port}"

    @property
    def auth_header(self) -> str:
        raw = f"riot:{self.password}".encode()
        return "Basic " + base64.b64encode(raw).decode()


def _from_process() -> Path | None:
    """从正在跑的客户端进程命令行里抠出安装目录——最可靠的一招。"""
    if os.name != "nt":
        return None
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" "
        "| Select-Object -First 1 -ExpandProperty CommandLine"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
    except Exception:
        return None
    if not out:
        return None
    for token in out.split('"'):
        if "--install-directory=" in token:
            d = token.split("--install-directory=", 1)[1].strip().strip('"')
            p = Path(d) / "lockfile"
            if p.exists():
                return p
    return None


def _from_registry() -> list[Path]:
    """从注册表读安装目录——国服由腾讯启动器写 InstallPath，最稳。"""
    if os.name != "nt":
        return []
    try:
        import winreg
    except Exception:
        return []
    roots = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    out: list[Path] = []
    for sub, value, hive in REGISTRY_KEYS:
        try:
            with winreg.OpenKey(roots[hive], sub) as key:
                raw, _ = winreg.QueryValueEx(key, value)
        except OSError:
            continue
        if not raw:
            continue
        d = Path(str(raw))
        for p in (d / "lockfile", d / "LeagueClient" / "lockfile"):
            if p.exists():
                out.append(p)
    return out


def _scan_drives() -> list[Path]:
    """兜底：在各盘按常见两层结构找 lockfile（客户端不写注册表时用）。"""
    patterns = [
        r"{d}:\League of Legends\*\\lockfile",
        r"{d}:\*\League of Legends\lockfile",
        r"{d}:\*\英雄联盟\lockfile",
        r"{d}:\Riot Games\*\lockfile",
        r"{d}:\*\Riot Games\League of Legends\lockfile",
        r"{d}:\WeGameApps\*\lockfile",
        r"{d}:\Games\*\lockfile",
    ]
    found: list[Path] = []
    for letter in DRIVE_LETTERS:
        drive = f"{letter}:"
        if not Path(drive + "\\").exists():
            continue
        for pat in patterns:
            for hit in glob.glob(pat.format(d=letter)):
                p = Path(hit)
                if p.is_file():
                    found.append(p)
    return found


def _scan_recent_lockfiles(max_age_days: float | None = 3.0, max_depth: int = 6) -> list[Path]:
    """按"最近改过"来捞 lockfile，不管它装在哪。

    朋友的机器上就踩过这个坑：注册表里记的是 2021 年的旧安装目录，
    lockfile 停在那一年，而真正的客户端装在别处。
    """
    cutoff = (time.time() - max_age_days * 86400) if max_age_days else 0.0
    found: list[Path] = []
    for letter in DRIVE_LETTERS:
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        base_depth = len(root.parts)
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                depth = len(Path(dirpath).parts) - base_depth
                if depth >= max_depth:
                    dirnames[:] = []
                # 跳过明显无关的大目录
                dirnames[:] = [
                    d for d in dirnames
                    if d.lower() not in (
                        "windows", "programdata", "$recycle.bin", "system volume information",
                        "node_modules", "appdata",
                    )
                ]
                if "lockfile" in filenames:
                    cand = Path(dirpath) / "lockfile"
                    try:
                        if cand.stat().st_mtime >= cutoff:
                            found.append(cand)
                    except OSError:
                        pass
        except OSError:
            continue
    return found


def selfcheck() -> list[str]:
    """一键体检：所有端口线索 + 每个的判定结果，写进诊断日志。"""
    out: list[str] = []

    def emit(line: str) -> None:
        out.append(line)
        diag.info(line)

    emit("=== 自检开始 ===")
    emit("注册表安装目录 : %s" % (", ".join(str(d) for d in _installed_dirs()) or "无"))

    proc = _ports_from_process()
    emit("进程命令行端口 : %s" % (proc or "没拿到（LeagueClientUx.exe 可能没在跑）"))

    locks = _scan_recent_lockfiles(max_age_days=None, max_depth=6)
    emit("磁盘上的 lockfile（%d 个）:" % len(locks))
    for lp in sorted(locks, key=lambda q: -q.stat().st_mtime)[:15]:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(lp.stat().st_mtime))
        emit("  %-70s [%s] %d 字节" % (str(lp)[:70], when, lp.stat().st_size))

    dirs = _log_dirs()
    emit("日志目录（%d 个）:" % len(dirs))
    for d in dirs:
        try:
            logs = sorted(d.glob("*.log"), key=lambda q: q.stat().st_mtime, reverse=True)
        except OSError:
            logs = []
        hit = 0
        newest = "-"
        if logs:
            newest = time.strftime("%Y-%m-%d %H:%M", time.localtime(logs[0].stat().st_mtime))
            for f in logs[:10]:
                try:
                    if _LOG_URL_RE.search(f.read_text(encoding="utf-8", errors="ignore")):
                        hit += 1
                except OSError:
                    pass
        emit("  %-60s 文件 %3d 个，最新 %s，含端口信息 %d 个" % (str(d)[:60], len(logs), newest, hit))

    emit("逐个端口判定：")
    eps = all_endpoints()
    if not eps:
        emit("  （一个候选都没有）")
    for lock, source in eps:
        if not _port_alive(lock.port, timeout=0.6):
            verdict = "端口没开"
        elif _authorized(lock):
            verdict = "可用 ← 就是这个"
        else:
            verdict = "活着但不是英雄联盟客户端"
        emit("  端口 %-6s %-14s %s" % (lock.port, verdict, source[:70]))

    emit("=== 自检结束 ===")
    return out


def client_dir(lock: Path) -> Path:
    return lock.parent


def _parse_quiet(path: Path) -> "Lockfile | None":
    try:
        return Lockfile.parse(path.read_text("utf-8", "ignore"))
    except Exception:
        return None


def _port_alive(port: int, timeout: float = 0.6) -> bool:
    """客户端没开时 lockfile 会留在原地，只有端口能连通才算真的活着。"""
    import socket

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _ports_from_process() -> list[tuple[int, str, str]]:
    """从正在跑的 LeagueClientUx 进程命令行里直接拿端口和 token。

    命令行里有 --app-port=12345 --remoting-auth-token=xxxx，这是最权威的来源，
    不依赖任何锁文件。
    """
    if os.name != "nt":
        return []
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='LeagueClientUx.exe'\" "
        "| Select-Object -ExpandProperty CommandLine"
    )
    out = ""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout or ""
    except Exception:
        out = ""
    if not out.strip():
        # Win10 还有 wmic，当备用
        try:
            out = subprocess.run(
                ["wmic", "process", "where", "name='LeagueClientUx.exe'", "get", "commandline"],
                capture_output=True, text=True, timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout or ""
        except Exception:
            out = ""

    found: list[tuple[int, str, str]] = []
    for chunk in out.splitlines():
        port_m = re.search(r"--app-port=(\d+)", chunk)
        token_m = re.search(r"--remoting-auth-token=([\w\-]+)", chunk)
        if port_m and token_m:
            found.append((int(port_m.group(1)), token_m.group(1), "客户端进程命令行"))
    return found


def _candidates(extra: str | None) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []

    def add(p: Path | None, why: str) -> None:
        if p and Path(p).exists() and all(Path(p) != q for q, _ in out):
            out.append((Path(p), why))

    if extra:
        add(Path(extra), "手动指定的锁文件")
    env = os.environ.get("RIFTSTATS_LOCKFILE")
    if env:
        add(Path(env), "环境变量 RIFTSTATS_LOCKFILE")
    for p in DEFAULT_PATHS:
        add(Path(p), f"常见路径 {p}")
    for sub, value, hive in REGISTRY_KEYS:
        d = _registry_dir(sub, value, hive)
        if d:
            add(d / "lockfile", f"注册表 {hive}\\{sub}")
            add(d / "LeagueClient" / "lockfile", f"注册表 {hive}\\{sub}")
    for p in _scan_recent_lockfiles():
        add(p, f"最近修改过的 lockfile（{time.strftime('%Y-%m-%d', time.localtime(p.stat().st_mtime))}）")
    # 兜底：就算很久没改过也试一遍，按修改时间从新到旧
    leftovers = sorted(
        _scan_recent_lockfiles(max_age_days=None), key=lambda q: -q.stat().st_mtime
    )
    for p in leftovers[:6]:
        add(p, f"磁盘上的 lockfile（{time.strftime('%Y-%m-%d', time.localtime(p.stat().st_mtime))}）")
    p = _from_process()
    if p:
        add(p, "运行中的客户端进程")
    for p in _scan_drives():
        add(p, f"扫描磁盘 {p}")
    return out


def _registry_dir(sub: str, value: str, hive: str) -> Path | None:
    if os.name != "nt":
        return None
    try:
        import winreg
    except Exception:
        return None
    root = winreg.HKEY_CURRENT_USER if hive == "HKCU" else winreg.HKEY_LOCAL_MACHINE
    try:
        with winreg.OpenKey(root, sub) as key:
            raw, _ = winreg.QueryValueEx(key, value)
    except OSError:
        return None
    if not raw:
        return None
    d = Path(str(raw))
    return d if d.exists() else None


def all_endpoints(extra: str | None = None) -> list[tuple[Lockfile, str]]:
    """汇总所有可能的 (端口, 密码) 来源，按可信度排序、去重。"""
    out: list[tuple[Lockfile, str]] = []
    seen: set[int] = set()

    def add(lock: Lockfile | None, source: str) -> None:
        if lock is None or lock.port in seen:
            return
        seen.add(lock.port)
        out.append((lock, source))

    if extra:
        add(_parse_quiet(Path(extra)), f"手动指定 {extra}")
    env = os.environ.get("RIFTSTATS_LOCKFILE")
    if env:
        add(_parse_quiet(Path(env)), "环境变量 RIFTSTATS_LOCKFILE")

    for port, token, source in _ports_from_process():
        add(Lockfile("LeagueClientUx", 0, port, token, "https"), source)

    for path, why in _candidates(extra):
        add(_parse_quiet(path), f"{path}（{why}）")

    for lock, log_path in _from_logs():
        add(lock, f"日志 {log_path.name}")

    return out


def diagnose(extra: str | None = None) -> tuple[Lockfile | None, str]:
    """把所有可能的端口挨个验一遍，第一个通过 /lol-summoner 的就是答案。

    不依赖"找到正确的那一个 lockfile"——国服客户端经常不写锁文件，
    而且机器上可能躺着好几个不同年份的旧文件。
    """
    diag.info("开始探测客户端端口…")
    endpoints = all_endpoints(extra)
    diag.info("共收集到 %d 个候选端口" % len(endpoints))

    tried: list[tuple[int, str, str]] = []
    for lock, source in endpoints:
        if not _port_alive(lock.port, timeout=0.6):
            tried.append((lock.port, source, "端口没开（客户端没运行）"))
            diag.info("  端口 %s 没开（%s）" % (lock.port, source))
            continue
        if _authorized(lock):
            diag.info("  端口 %s 可用（%s）" % (lock.port, source))
            return lock, "已连上客户端：端口 %d（来源：%s）" % (lock.port, source)
        tried.append((lock.port, source, "端口活着但不是英雄联盟客户端"))
        diag.warn("  端口 %s 拒绝 /lol-summoner（%s）" % (lock.port, source))

    if tried:
        lines = ["没找到可用的英雄联盟客户端。试过 %d 个端口：" % len(tried)]
        for port, source, why in tried[:8]:
            lines.append("  · %s → %s" % (source, why))
        lines.append("请确认客户端已启动并进入大区；也可以点「生成自检报告」把详情记下来。")
        return None, "\n".join(lines)

    return None, (
        "没有找到任何端口线索：lockfile、客户端日志、进程命令行里都没有。\n"
        "说明英雄联盟客户端此刻没有运行（可能只开了 WeGame / 启动器）。\n"
        "请进入客户端主界面后再点一次检测。"
    )


def _authorized(lock: "Lockfile", timeout: float = 4.0) -> bool:
    """带认证发一个最轻的请求，确认端口后面是真的客户端。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # 注意：必须用 /lol-* 验证。Riot Client 也有 /riotclient/region-locale，
    # 但它是启动器，不是英雄联盟客户端，对它调 /lol-* 全是 404。
    req = urllib.request.Request(
        lock.base_url + "/lol-summoner/v1/current-summoner",
        headers={"Authorization": lock.auth_header, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            diag.warn("端口 %s 是 Riot Client（启动器），不是英雄联盟客户端" % lock.port)
        return False
    except Exception:
        return False


_LOG_URL_RE = re.compile(r"https://riot:([^@\s]+)@127\.0\.0\.1:(\d+)")


def _log_dirs() -> list[Path]:
    dirs: list[Path] = []

    def add(p: Path) -> None:
        if p.is_dir() and p not in dirs:
            dirs.append(p)

    for d in _installed_dirs():
        add(d / "LeagueClient")
        add(d / "Logs")
        add(d / "Riot Client" / "log")
        add(d / "Game" / "Logs")
        add(d / "Game" / "Logs" / "LeagueClient Logs")
    for p in DEFAULT_PATHS:
        d = Path(p).parent
        add(d / "LeagueClient")
        add(d / "Riot Client" / "log")
    return dirs


def _from_logs() -> list[tuple[Lockfile, Path]]:
    """从客户端最近的日志里扒端口和密码。

    日志里那条记录长这样：
      https://riot:M2WdgHBEIFEIAQqWKmPUsA@127.0.0.1:56439/index.html
    国服实测 lockfile 是 0 字节，这条是唯一可靠的来源。
    """
    out: list[tuple[Lockfile, Path]] = []
    seen: set[tuple[int, str]] = set()
    for d in _log_dirs():
        try:
            logs = sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:6]
        except OSError:
            continue
        for log in logs:
            try:
                with open(log, "r", encoding="utf-8", errors="ignore") as fh:
                    chunk = fh.read(400_000)
            except OSError:
                continue
            last = None
            for m in _LOG_URL_RE.finditer(chunk):
                last = m  # 取最后一条，通常是最新的
            if last is None:
                continue
            password, port = last.group(1), int(last.group(2))
            if (port, password) in seen:
                continue
            seen.add((port, password))
            out.append((Lockfile("LeagueClientUx", 0, port, password, "https"), log))
    return out


def _installed_dirs() -> list[Path]:
    out: list[Path] = []
    for sub, value, hive in REGISTRY_KEYS:
        d = _registry_dir(sub, value, hive)
        if d and d not in out:
            out.append(d)
    return out


def find_lockfile(extra: str | None = None) -> Path | None:
    """兼容旧接口：能落到文件上的才返回路径，国服日志路线返回 None。"""
    lock, _why = diagnose(extra)
    if lock is None:
        return None
    for path, _ in _candidates(extra):
        parsed = _parse_quiet(path)
        if parsed and parsed.port == lock.port and parsed.password == lock.password:
            return path
    return None


class LcuClient:
    def __init__(self, lock: Lockfile) -> None:
        self.lock = lock
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE
        self._champion_map: dict[int, str] | None = None

    # ---- 底层 ------------------------------------------------------------
    def get(self, path: str, timeout: float = 10.0):
        url = self.lock.base_url + path
        req = urllib.request.Request(
            url, headers={"Authorization": self.lock.auth_header, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=self._ctx) as resp:
                body = resp.read()
        except Exception as exc:
            detail = ""
            reader = getattr(exc, "read", None)
            if callable(reader):
                try:
                    detail = " | " + reader().decode("utf-8", "ignore")[:300]
                except Exception:
                    pass
            code = getattr(exc, "code", "?")
            if code != 404:  # 404 只是"这局不是我的"，不算故障
                diag.error(
                    "GET %s 失败 code=%s %s: %s%s"
                    % (path, code, type(exc).__name__, exc, detail)
                )
            raise
        return json.loads(body.decode("utf-8", "ignore")) if body else None

    # ---- 常用接口 --------------------------------------------------------
    def current_summoner(self) -> dict:
        return self.get("/lol-summoner/v1/current-summoner") or {}

    def gameflow_phase(self) -> str:
        try:
            return self.get("/lol-gameflow/v1/gameflow-phase") or "None"
        except Exception:
            return "Unknown"

    def champion_names(self) -> dict[int, str]:
        if self._champion_map is not None:
            return self._champion_map
        mapping: dict[int, str] = {}
        cache = data_dir() / "champions.json"
        try:
            data = self.get("/lol-game-data/assets/v1/champion-summary.json")
            for item in data or []:
                cid = item.get("id")
                if isinstance(cid, int) and cid > 0:
                    mapping[cid] = item.get("name") or item.get("alias") or str(cid)
            if mapping:
                cache.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        if not mapping and cache.exists():
            try:
                mapping = {int(k): v for k, v in json.loads(cache.read_text("utf-8")).items()}
            except Exception:
                mapping = {}
        self._champion_map = mapping
        return mapping

    def recent_match_ids(self, count: int = 20) -> list[int]:
        data = self.get(
            f"/lol-match-history/v1/products/lol/current-summoner/matches"
            f"?begIndex=0&endIndex={max(count, 1)}"
        ) or {}
        games = (data.get("games") or {}).get("games") or []
        return [int(g["gameId"]) for g in games if g.get("gameId")]

    def recent_window(self, puuid: str = "", size: int = 20) -> list[int]:
        """客户端本地只缓存一页（20 场），begIndex 会被忽略。

        想拿更多历史只有一个办法：让客户端的"对局记录"翻页，然后把每一页抓下来。
        见 harvest()。
        """
        who = puuid or "current-summoner"
        data = self.get(
            f"/lol-match-history/v1/products/lol/{who}/matches?begIndex=0&endIndex={size}"
        ) or {}
        games = (data.get("games") or {}).get("games") or []
        return [int(g["gameId"]) for g in games if g.get("gameId")]

    def match_detail(self, game_id: int, timeout: float = 10.0) -> dict:
        return self.get(f"/lol-match-history/v1/games/{game_id}", timeout=timeout) or {}


# ---- 解析 -----------------------------------------------------------------
def _int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def parse_match_detail(detail: dict, self_puuid: str, champs: dict[int, str] | None = None) -> Match | None:
    """把 LCU 的 /lol-match-history/v1/games/{id} 归一化成 Match。"""
    if not detail:
        return None
    champs = champs or {}
    puuids: dict[int, str] = {}
    names: dict[int, str] = {}
    for ident in detail.get("participantIdentities") or []:
        pid = _int(ident.get("participantId"))
        player = ident.get("player") or {}
        puuids[pid] = player.get("puuid") or ""
        names[pid] = (
            player.get("summonerName")
            or player.get("gameName")
            or player.get("displayName")
            or f"玩家{pid}"
        )

    self_id = None
    for pid, uuid in puuids.items():
        if uuid and uuid == self_puuid:
            self_id = pid
            break

    parts: list[Participant] = []
    self_side = BLUE
    for row in detail.get("participants") or []:
        pid = _int(row.get("participantId"))
        stats = row.get("stats") or {}
        side = _int(row.get("teamId"), BLUE)
        cid = _int(row.get("championId"))
        is_self = pid == self_id
        if is_self:
            self_side = side
        parts.append(
            Participant(
                name=names.get(pid, f"玩家{pid}"),
                side=side,
                slot=len([p for p in parts if p.side == side]),
                champion=row.get("championName") or champs.get(cid, ""),
                kills=_int(stats.get("kills", stats.get("CHAMPIONS_KILLED"))),
                deaths=_int(stats.get("deaths", stats.get("NUM_DEATHS"))),
                assists=_int(stats.get("assists", stats.get("ASSISTS"))),
                damage_dealt=_int(
                    stats.get("totalDamageDealtToChampions",
                              stats.get("TOTAL_DAMAGE_DEALT_TO_CHAMPIONS"))
                ),
                damage_taken=_int(stats.get("totalDamageTaken", stats.get("TOTAL_DAMAGE_TAKEN"))),
                gold=_int(stats.get("goldEarned", stats.get("GOLD_EARNED"))),
                cs=_int(stats.get("totalMinionsKilled", stats.get("TOTAL_MINIONS_KILLED"))),
                vision=_int(stats.get("visionScore", stats.get("VISION_SCORE"))),
                is_self=is_self,
                puuid=puuids.get(pid, ""),
                items=[
                    _int(stats.get("item%d" % i))
                    for i in range(7)
                    if _int(stats.get("item%d" % i))
                ],
                augments=[
                    _int(stats.get("playerAugment%d" % i))
                    for i in range(1, 7)
                    if _int(stats.get("playerAugment%d" % i))
                ],
            )
        )

    me = next((p for p in parts if p.is_self), None)
    if me is None:
        return None
    me_side = [p for p in parts if p.side == self_side]
    for i, p in enumerate(sorted(me_side, key=lambda x: x.slot)):
        p.slot = i

    win = False
    for row in detail.get("participants") or []:
        if _int(row.get("participantId")) == self_id:
            st = row.get("stats") or {}
            win = bool(st.get("win", st.get("WIN", False)))
            break

    duration = _int(detail.get("gameDuration"), 0)
    if duration > 100000:  # 毫秒
        duration //= 1000

    return Match(
        match_id=f"lcu:{detail.get('gameId')}",
        created_at=_int(detail.get("gameCreation")) // 1000,
        duration_s=duration,
        mode=detail.get("gameMode") or "CLASSIC",
        win=win,
        self_side=me.side,
        self_slot=me.slot,
        self_name=me.name,
        self_puuid=self_puuid,
        source="lcu",
        participants=parts,
    )


def fetch_matches(limit: int = 20, client: LcuClient | None = None) -> tuple[list[Match], list[str]]:
    """连客户端拉最近对局。返回 (对局列表, 日志)。"""
    log: list[str] = []
    if client is None:
        lock, why = diagnose()
        if lock is None:
            return [], [why]
        log.append(f"连接来源：{why}")
        client = LcuClient(lock)

    try:
        me = client.current_summoner()
        puuid = me.get("puuid") or ""
        log.append(f"已连接：{me.get('gameName') or me.get('displayName') or '未知召唤师'}（{puuid[:8]}…）")
    except Exception as exc:
        return [], [f"无法访问客户端接口：{exc}"]

    ids = client.recent_match_ids(limit)
    log.append(f"取到 {len(ids)} 场对局 ID")
    champs = client.champion_names()
    out: list[Match] = []
    for gid in ids:
        try:
            m = parse_match_detail(client.match_detail(gid), puuid, champs)
        except Exception as exc:
            log.append(f"  {gid} 解析失败：{exc}")
            continue
        if m:
            out.append(m)
    log.append(f"成功解析 {len(out)} 场")
    return out, log


def harvest(
    store,
    duration_s: int = 240,
    interval: float = 1.2,
    progress=None,
    should_stop=None,
) -> dict:
    """边滚边抓：客户端"对局记录"每翻一页，就把那一页的 20 场吃进来。

    国服客户端本地只缓存一页，begIndex 参数会被无视（实测 8 种参数、60 秒过期、
    POST 刷新全都不行），所以只能跟着 UI 的翻页节奏走。你往下滚一次，这里就多 20 场。
    """
    say = progress or (lambda _msg: None)
    lock, why = diagnose()
    if lock is None:
        return {"error": why, "saved": 0, "pages": 0}
    client = LcuClient(lock)
    me = client.current_summoner()
    puuid = me.get("puuid") or ""
    name = me.get("gameName") or me.get("displayName") or "?"
    say(f"已连接 {name}（{why}）")

    champs = client.champion_names()
    seen: set[int] = set()
    windows: set[tuple[int, ...]] = set()
    pages = 0
    deadline = time.time() + duration_s
    say("请在客户端打开「对局记录」并往下滚，滚到哪儿这里就抓到哪儿。")

    while time.time() < deadline:
        if should_stop and should_stop():
            say("已手动停止")
            break
        try:
            ids = client.recent_window(puuid, 20)
        except Exception as exc:
            say(f"读取窗口失败：{exc}")
            time.sleep(interval)
            continue
        key = tuple(ids)
        if ids and key not in windows:
            windows.add(key)
            new = [gid for gid in ids if gid not in seen]
            saved = 0
            for gid in new:
                try:
                    m = parse_match_detail(client.match_detail(gid), puuid, champs)
                except Exception:
                    continue
                if m and store.upsert(m):
                    saved += 1
                if m:
                    seen.add(gid)
            pages += 1
            first = f"{ids[0]}"
            say(f"第 {pages} 个窗口（首场 {first}）：新增入库 {saved} 场，累计 {len(seen)} 场")
        time.sleep(interval)

    return {"saved": len(seen), "pages": pages, "error": None}


_LOG_ID_RE = re.compile(r"\b1[0-9]{10}\b")


def ids_from_logs(progress=None, min_mtime: float | None = None) -> list[int]:
    """从客户端/Riot Client 的日志里翻出历史出现过的 gameId。

    日志里会打印每一场对局的 id（匹配成功、对战记录刷新等），一个月的日志能凑出
    几百个候选。候选里混着别人的 id 和误报，交给调用方用 /games/{id} 验证。

    min_mtime：只扫这个时间点之后改动过的日志文件（限范围时能省不少时间）。
    """
    from concurrent.futures import ThreadPoolExecutor

    say = progress or (lambda _m: None)
    files: list[str] = []
    skipped = 0
    for root in _scan_roots():
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.lower().endswith((".log", ".json", ".txt")):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.getsize(p) > 20_000_000:
                        continue
                    if min_mtime is not None and os.path.getmtime(p) < min_mtime:
                        skipped += 1
                        continue
                except OSError:
                    continue
                files.append(p)

    def read_ids(path: str) -> set[int]:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                data = fh.read()
        except OSError:
            return set()
        return {int(m.group(0)) for m in _LOG_ID_RE.finditer(data)}

    ids: set[int] = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for got in pool.map(read_ids, files):
            ids |= got

    extra = f"，跳过 {skipped} 个过旧的文件" if skipped else ""
    say(f"扫了 {len(files)} 个文件{extra}，拿到 {len(ids)} 个候选 id")
    return sorted(ids, reverse=True)


def _scan_roots() -> list[str]:
    roots = [str(d) for d in _installed_dirs()]
    for p in DEFAULT_PATHS:
        d = str(Path(p).parent)
        if d not in roots and Path(d).is_dir():
            roots.append(d)
    appdata = os.environ.get("APPDATA")
    if appdata:
        for sub in ("Tencent\\WeGame", "Tencent"):
            cand = os.path.join(appdata, sub)
            if os.path.isdir(cand) and cand not in roots:
                roots.append(cand)
    return roots


def _id_time_model(store, client, puuid: str, probe_ids: list[int]) -> tuple[float, float] | None:
    """估算 (当前时刻的 gameId, 每秒涨多少 id)。

    优先用库里已有对局的 (时间, id) 拟合；没有就抓当前窗口 20 场的细节。
    有这个才能在验证之前把"比时间范围更老"的候选直接裁掉。
    """
    pairs: list[tuple[float, int]] = []
    for m in store.all()[:500]:
        if not m.match_id.startswith("lcu:"):
            continue
        try:
            pairs.append((float(m.created_at), float(int(m.match_id.split(":", 1)[1]))))
        except (ValueError, IndexError):
            continue

    if len(pairs) < 5 and probe_ids:
        from concurrent.futures import ThreadPoolExecutor

        def fetch(gid: int):
            try:
                d = client.match_detail(gid, timeout=6.0)
            except Exception:
                return None
            ts = d.get("gameCreation")
            if not ts:
                return None
            return (float(ts) / 1000.0, float(gid))

        with ThreadPoolExecutor(max_workers=8) as pool:
            for got in pool.map(fetch, probe_ids[:20]):
                if got:
                    pairs.append(got)

    if len(pairs) < 2:
        return None
    pairs.sort(key=lambda x: x[0])
    (t0, i0), (t1, i1) = pairs[0], pairs[-1]
    if t1 <= t0 or i1 <= i0:
        return None
    rate = (i1 - i0) / (t1 - t0)
    now_id = i1 + (time.time() - t1) * rate
    return now_id, rate


def harvest_from_logs(
    store,
    progress=None,
    should_stop=None,
    limit: int | None = None,
    workers: int = 12,
    max_fail_streak: int = 15,
    days: int | None = None,
) -> dict:
    """用日志里的 gameId 反查历史对局：/lol-match-history/v1/games/{id} 对任意老对局有效。

    防呆：先探一次当前客户端能不能返回对局详情，不能就立刻退出；
    跑到一半如果连续 15 个候选都失败，也直接收工——不然会空转几十分钟。
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    say = progress or (lambda _m: None)
    diag.info("开始从日志恢复历史：范围 %s 天" % (days or "全部"))
    lock, why = diagnose()
    if lock is None:
        diag.error("恢复历史失败：%s" % why)
        return {"error": why, "saved": 0, "checked": 0}
    client = LcuClient(lock)
    me = client.current_summoner()
    puuid = me.get("puuid") or ""
    name = me.get("gameName") or "?"
    say(f"已连接 {name}")

    # 先探活：拿当前窗口里的一场试试，拿不到说明没登录进大区，后面全是白跑
    probe_ok = False
    try:
        probe_ids = client.recent_window(puuid, 5)
    except Exception:
        probe_ids = []
    for gid in probe_ids[:3]:
        try:
            detail = client.match_detail(gid)
            if detail and detail.get("participants"):
                probe_ok = True
                break
        except Exception:
            continue
    if not probe_ok:
        return {
            "error": (
                "客户端连上了，但拉不到任何对局详情。\n"
                "多半是还没登录进大区（停在登录界面 / 选大区界面），"
                "或者当前账号没有对局记录。\n请先进入客户端主界面再试。"
            ),
            "saved": 0,
            "checked": 0,
        }
    say("预检通过：客户端能返回对局详情")

    cutoff = (time.time() - days * 86400) if days else None
    span = f"最近 {days} 天" if days else "全部历史"
    say(f"读取范围：{span}")

    min_mtime = (time.time() - days * 1.6 * 86400) if days else None
    ids = ids_from_logs(say, min_mtime=min_mtime)

    # 日志里混着大量非 gameId 的 11 位数（时间戳、QQ 号…），按当前对局 id 的
    # 量级筛一遍，省得一个个去试。一年前的老对局大约是当前 id 的 0.9 倍。
    if probe_ids:
        top = max(probe_ids)
        lo, hi = int(top * 0.60), int(top * 1.05)
        kept = [i for i in ids if lo <= i <= hi]
        if len(kept) != len(ids):
            say(f"按 id 量级过滤：{len(ids)} → {len(kept)} 个候选")
        ids = kept

    if days:
        model = _id_time_model(store, client, puuid, probe_ids)
        if model:
            now_id, rate = model
            cutoff_id = int(now_id - days * 86400 * rate * 1.15)
            before = len(ids)
            ids = [i for i in ids if i >= cutoff_id]
            say(
                f"按时间推算（每天约 {rate*86400:,.0f} 个 id）：{days} 天内候选 "
                f"{len(ids)} 个，裁掉更早的 {before - len(ids)} 个"
            )
    if limit:
        ids = ids[:limit]
    known = {mid.split(":", 1)[1] for mid in store.known_ids() if mid.startswith("lcu:")}
    todo = [gid for gid in ids if str(gid) not in known]
    say(f"其中 {len(todo)} 个是库里还没有的，开始验证（{workers} 线程并发）")
    if not todo:
        return {"saved": 0, "checked": 0, "error": None}

    champs = client.champion_names()
    saved = 0
    done = 0
    fail_streak = 0
    started = time.time()
    oldest_hit = None  # 已命中对局里最老的时间戳

    def check(gid: int):
        """返回 (match, status)。status: hit / miss / error。

        miss = 接口正常回了 404（这局不是我的），不能算故障；
        只有 error（超时、连接被拒）才计入连续失败。
        """
        for attempt in range(2):
            try:
                m = parse_match_detail(client.match_detail(gid, timeout=6.0), puuid, champs)
                return m, ("hit" if m else "miss")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return None, "miss"
            except Exception:
                pass
            if attempt == 0:
                time.sleep(0.12)
        return None, "error"

    aborted = None
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(check, gid): gid for gid in todo}
        for fut in as_completed(futures):
            done += 1
            m, status = fut.result()
            fail_streak = fail_streak + 1 if status == "error" else 0
            if m:
                if cutoff and m.created_at < cutoff:
                    # 比范围更老，不入库，但用它的时间戳判断是否该收工
                    if oldest_hit is None or m.created_at < oldest_hit:
                        oldest_hit = m.created_at
                    continue
                if store.upsert(m):
                    saved += 1
            if done % 25 == 0 or done == len(todo):
                spent = time.time() - started
                eta = spent / done * (len(todo) - done)
                say(f"进度 {done}/{len(todo)}：命中 {saved} 场，剩余约 {eta:.0f} 秒")
                if cutoff and oldest_hit and oldest_hit < cutoff:
                    say(f"已经挖到 {span} 之前的对局（{time.strftime('%Y-%m-%d', time.localtime(oldest_hit))}），提前收工")
                    for f in futures:
                        f.cancel()
                    break
            if fail_streak >= max_fail_streak:
                aborted = (
                    f"连续 {fail_streak} 个请求都出错，已停止。"
                    "客户端可能掉线了，稍后再试一次。"
                )
                say(aborted)
                for f in futures:
                    f.cancel()
                break
            if should_stop and should_stop():
                for f in futures:
                    f.cancel()
                say("已停止")
                break
    return {"saved": saved, "checked": done, "error": None, "aborted": aborted}
