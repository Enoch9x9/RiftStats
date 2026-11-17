"""数据模型：一局比赛 + 10 个参与者。

所有数据源（LCU / Riot API / 截图识别 / 手动录入）最后都归一化成这两个类，
后面的统计和界面只认这里，不再关心数据从哪来。
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any

BLUE = 100
RED = 200

ROLE_NAMES = ["上单", "打野", "中单", "下路", "辅助"]


@dataclass
class Participant:
    """一个玩家的赛后数据。"""

    name: str  # 召唤师 ID（截图里那一串）
    side: int = BLUE  # 100 = 蓝方, 200 = 红方
    slot: int = 0  # 0..4，按截图从上到下
    champion: str = ""
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    damage_dealt: int = 0  # 对英雄伤害（英雄输出）
    damage_taken: int = 0  # 承受伤害
    gold: int = 0
    cs: int = 0
    vision: int = 0
    is_self: bool = False
    puuid: str = ""
    summoner_id: str = ""

    @property
    def kda(self) -> float:
        return (self.kills + self.assists) / max(self.deaths, 1)

    @property
    def role(self) -> str:
        return ROLE_NAMES[self.slot] if 0 <= self.slot < 5 else "?"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Participant":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Match:
    match_id: str
    created_at: int  # epoch 秒
    duration_s: int
    mode: str
    win: bool
    self_side: int = BLUE
    self_slot: int = 0
    self_name: str = ""
    self_puuid: str = ""
    source: str = "manual"  # lcu / riot / image / manual / demo
    participants: list[Participant] = field(default_factory=list)
    raw: dict[str, Any] | None = None

    # ---- 派生 -----------------------------------------------------------
    @property
    def me(self) -> Participant | None:
        for p in self.participants:
            if p.is_self:
                return p
        return None

    def team(self, side: int) -> list[Participant]:
        return sorted([p for p in self.participants if p.side == side], key=lambda p: p.slot)

    @property
    def my_team(self) -> list[Participant]:
        return self.team(self.self_side)

    @property
    def enemy_team(self) -> list[Participant]:
        other = RED if self.self_side == BLUE else BLUE
        return self.team(other)

    def has_player(self, name: str) -> bool:
        low = name.strip().lower()
        return any(p.name.strip().lower() == low for p in self.participants)

    def player_for(self, name: str | None) -> Participant | None:
        """按名字取参与者；name 为空就回到"我自己"。"""
        if not name:
            return self.me
        low = name.strip().lower()
        for p in self.participants:
            if p.name.strip().lower() == low:
                return p
        return self.me

    def team_of(self, p: Participant | None) -> list[Participant]:
        return self.team(p.side) if p else self.my_team

    def share_for(self, p: Participant | None) -> float:
        if not p:
            return 0.0
        total = sum(x.damage_dealt for x in self.team(p.side))
        return (p.damage_dealt / total) if total else 0.0

    def teammates_of(self, name: str | None) -> list[Participant]:
        p = self.player_for(name)
        if not p:
            return []
        return [x for x in self.team(p.side) if x is not p]

    @property
    def teammates(self) -> list[Participant]:
        return [p for p in self.my_team if p is not self.me and not p.is_self]

    @property
    def team_damage(self) -> int:
        return sum(p.damage_dealt for p in self.my_team)

    @property
    def damage_share(self) -> float:
        """自己在队内总输出里的占比，0~1。"""
        total = self.team_damage
        me = self.me
        return (me.damage_dealt / total) if (me and total) else 0.0

    @property
    def duration_min(self) -> float:
        return max(self.duration_s, 60) / 60.0

    @property
    def created_at_str(self) -> str:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.created_at))

    def to_row(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d

    @classmethod
    def from_row(cls, d: dict[str, Any]) -> "Match":
        d = dict(d)
        parts = [Participant.from_dict(p) for p in d.pop("participants", [])]
        m = cls(**d)
        m.participants = parts
        return m


def teammate_names(match: Match) -> list[str]:
    return [p.name for p in match.teammates if p.name]


def make_match_id(source: str, key: str) -> str:
    return f"{source}:{key}"


MODE_NAMES = {
    "KIWI": "海克斯大乱斗",  # 国服嚎哭深渊（带海克斯强化）的内部代号，mapId=12
    "KIWI_JADE": "海克斯大乱斗·变体",
    "ARAM": "大乱斗",
    "CLASSIC": "召唤师峡谷",
    "URF": "无限火力",
    "CHERRY": "斗魂竞技场",
    "TUTORIAL": "新手教学",
    "PRACTICETOOL": "训练营",
}

MAP_NAMES = {
    11: "召唤师峡谷",
    12: "大乱斗",
    30: "斗魂竞技场",
    35: "斗魂竞技场",
}


def mode_display(mode: str) -> str:
    return MODE_NAMES.get((mode or "").upper(), mode or "—")
