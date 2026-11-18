"""装备 / 海克斯强化的数据层：从客户端本地资源建 ID→中文名 的对照表。"""

from __future__ import annotations

import json
from pathlib import Path

from .store import data_dir

_CACHE: dict[int, str] = {}
_AUG_CACHE: dict[int, str] = {}
_LOADED = False


def cache_path(which: str) -> Path:
    return data_dir() / "catalog" / f"{which}.json"


def _better_name(item: dict) -> str:
    """强化名字偶尔是空的（有 id 名字全空格），按优先级回退。"""
    for key in ("nameTRA", "simpleNameTRA", "name", "tooltip_name", "englishName"):
        value = (item.get(key) or "").strip()
        if value:
            return value
    return ""


def load_local() -> bool:
    """先尝试读本地缓存；没有就返回 False。"""
    global _LOADED
    ok = False
    for which, target in (("items", _CACHE), ("augments", _AUG_CACHE)):
        p = cache_path(which)
        if not p.exists():
            continue
        try:
            for row in json.loads(p.read_text(encoding="utf-8")):
                name = _better_name(row)
                if name:
                    target[int(row["id"])] = name
            ok = True
        except Exception:
            pass
    _LOADED = ok
    return ok


def fetch_from_client(client) -> int:
    """从客户端本地资源拉一次，存到 data/catalog/。返回条数。"""
    saved = 0
    specs = (
        ("items", "/lol-game-data/assets/v1/items.json", _CACHE),
        ("augments", "/lol-game-data/assets/v1/cherry-augments.json", _AUG_CACHE),
    )
    for which, path, target in specs:
        try:
            rows = client.get(path, timeout=20) or []
        except Exception:
            continue
        if not isinstance(rows, list) or not rows:
            continue
        p = cache_path(which)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        target.clear()
        for row in rows:
            name = _better_name(row)
            if name:
                target[int(row["id"])] = name
        saved += len(rows)
    global _LOADED
    _LOADED = saved > 0
    return saved


def item_name(item_id: int) -> str:
    if not item_id:
        return ""
    return _CACHE.get(item_id) or f"装备 #{item_id}"


def augment_name(aug_id: int) -> str:
    if not aug_id:
        return ""
    return _AUG_CACHE.get(aug_id) or f"强化 #{aug_id}"


def loaded() -> bool:
    return _LOADED
