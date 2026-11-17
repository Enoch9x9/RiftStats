"""SQLite 存储。便携模式：数据库跟 exe/项目走，不写 C 盘用户目录。"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

from .models import Match, Participant

SCHEMA_VERSION = 1


def app_dir() -> Path:
    """程序所在目录（打包后是 exe 旁边，源码运行是项目根）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    override = os.environ.get("RIFTSTATS_HOME")
    d = Path(override) if override else app_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "riftstats.db"


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 采集在后台线程跑，界面在主线程读，所以连接要跨线程 + 加锁
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self._init()

    # ---- 基础 ------------------------------------------------------------
    def _init(self) -> None:
        c = self._conn
        c.execute("PRAGMA journal_mode=WAL")
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                match_id   TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                duration_s INTEGER NOT NULL,
                mode       TEXT NOT NULL,
                win        INTEGER NOT NULL,
                self_name  TEXT,
                self_puuid TEXT,
                source     TEXT,
                payload    TEXT NOT NULL
            )
            """
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_matches_created ON matches(created_at DESC)"
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        c.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        c.commit()

    # ---- 写 --------------------------------------------------------------
    def upsert(self, match: Match) -> bool:
        """返回 True 表示是新插入的。"""
        with self._lock:
            return self._upsert_locked(match)

    def _upsert_locked(self, match: Match) -> bool:
        payload = json.dumps(match.to_row(), ensure_ascii=False)
        cur = self._conn.execute(
            "SELECT 1 FROM matches WHERE match_id = ?", (match.match_id,)
        )
        fresh = cur.fetchone() is None
        self._conn.execute(
            """
            INSERT INTO matches(match_id, created_at, duration_s, mode, win,
                                self_name, self_puuid, source, payload)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(match_id) DO UPDATE SET payload=excluded.payload,
                win=excluded.win, created_at=excluded.created_at
            """,
            (
                match.match_id,
                match.created_at,
                match.duration_s,
                match.mode,
                int(match.win),
                match.self_name,
                match.self_puuid,
                match.source,
                payload,
            ),
        )
        self._conn.commit()
        return fresh

    def delete(self, match_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM matches WHERE match_id = ?", (match_id,))
            self._conn.commit()

    def clear(self, source: str | None = None) -> None:
        with self._lock:
            if source:
                self._conn.execute("DELETE FROM matches WHERE source = ?", (source,))
            else:
                self._conn.execute("DELETE FROM matches")
            self._conn.commit()

    # ---- 读 --------------------------------------------------------------
    def all(self) -> list[Match]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload FROM matches ORDER BY created_at DESC"
            ).fetchall()
        out: list[Match] = []
        for r in rows:
            try:
                out.append(Match.from_row(json.loads(r["payload"])))
            except Exception:  # 坏数据不要炸整个界面
                continue
        return out

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0])

    def known_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT match_id FROM matches").fetchall()
            return {r["match_id"] for r in rows}

    def known_self_names(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT self_name FROM matches WHERE self_name IS NOT NULL"
            ).fetchall()
            return {r["self_name"] for r in rows if r["self_name"]}

    # ---- 设置（存 meta 表） ----------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM meta WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
