"""演示数据：让界面第一次打开就有东西看，同时验证统计链路。

这些对局的 match_id 都带 demo: 前缀，右上角一键就能清掉。
"""

from __future__ import annotations

import random
import time

from ..models import BLUE, RED, Match, Participant

# 全是编的，跟任何真实玩家无关。
# 这里的权重只影响演示数据的胜负走向，让"抓内鬼"有东西可看。
FRIENDS = ["老张不抓上路", "奶茶只要三分糖", "凌晨四点的猫", "只会玩辅助"]
FRIEND_EFFECT = {
    "老张不抓上路": 0.13,
    "奶茶只要三分糖": 0.05,
    "凌晨四点的猫": -0.05,
    "只会玩辅助": -0.19,
}
STRANGERS = [
    "电竞小学生",
    "打野在挂机",
    "闪现撞墙",
    "菜就多练",
    "中路第一深情",
    "辅助快跟我",
    "打不过就投",
    "峡谷养生局",
    "摸鱼选手",
    "不会打字",
    "野区散步",
    "躺赢专家",
]
CHAMPS = [
    "布里茨", "维鲁斯", "厄斐琉斯", "拉克丝", "泰达米尔", "盖伦", "亚索",
    "劫", "金克丝", "蕾欧娜", "莫甘娜", "阿狸", "艾希", "石头人", "提莫",
]
MODES = ["ARAM", "CLASSIC", "CLASSIC", "ARAM"]


def _damage(rng: random.Random, win: bool) -> int:
    base = rng.gauss(24000 if win else 19000, 5500)
    return int(max(4000, min(52000, base)))


def generate(count: int = 48, seed: int = 20261117, self_name: str = "示例玩家") -> list[Match]:
    rng = random.Random(seed)
    now = int(time.time())
    matches: list[Match] = []

    for i in range(count):
        created = now - i * rng.randint(1800, 7200) - rng.randint(0, 900)
        mode = rng.choice(MODES)
        duration = rng.randint(900, 2400) if mode == "ARAM" else rng.randint(1500, 2700)

        self_side = rng.choice([BLUE, RED])
        enemy_side = RED if self_side == BLUE else BLUE

        # 队友：好友 2 个 + 路人 2 个（大乱斗随机队友）
        mates = rng.sample(FRIENDS, 2) + rng.sample(STRANGERS, 2)
        rng.shuffle(mates)

        # 队友是谁会影响胜负，这样"抓内鬼"才有数据支撑
        p_win = 0.52 + sum(FRIEND_EFFECT.get(n, 0.0) for n in mates)
        win = rng.random() < max(0.12, min(0.88, p_win))

        parts: list[Participant] = []
        me_dmg = _damage(rng, win)
        parts.append(
            Participant(
                name=self_name,
                side=self_side,
                slot=0,
                champion=rng.choice(CHAMPS),
                kills=rng.randint(3, 14) if win else rng.randint(0, 9),
                deaths=rng.randint(2, 9) if win else rng.randint(5, 14),
                assists=rng.randint(8, 26) if win else rng.randint(3, 15),
                damage_dealt=me_dmg,
                damage_taken=int(me_dmg * rng.uniform(1.6, 2.8)),
                gold=rng.randint(9000, 16000),
                cs=rng.randint(30, 220),
                vision=rng.randint(8, 40),
                is_self=True,
            )
        )
        for slot, name in enumerate(mates, start=1):
            dmg = _damage(rng, win)
            parts.append(
                Participant(
                    name=name,
                    side=self_side,
                    slot=slot,
                    champion=rng.choice(CHAMPS),
                    kills=rng.randint(0, 15),
                    deaths=rng.randint(2, 13),
                    assists=rng.randint(2, 28),
                    damage_dealt=dmg,
                    damage_taken=int(dmg * rng.uniform(1.4, 3.0)),
                    gold=rng.randint(8000, 16000),
                    cs=rng.randint(20, 240),
                    vision=rng.randint(5, 40),
                )
            )
        for slot in range(5):
            dmg = _damage(rng, not win)
            parts.append(
                Participant(
                    name=rng.choice(STRANGERS),
                    side=enemy_side,
                    slot=slot,
                    champion=rng.choice(CHAMPS),
                    kills=rng.randint(0, 16),
                    deaths=rng.randint(2, 13),
                    assists=rng.randint(2, 28),
                    damage_dealt=dmg,
                    damage_taken=int(dmg * rng.uniform(1.4, 3.0)),
                    gold=rng.randint(8000, 16000),
                )
            )

        matches.append(
            Match(
                match_id=f"demo:{created}-{i}",
                created_at=created,
                duration_s=duration,
                mode=mode,
                win=win,
                self_side=self_side,
                self_slot=0,
                self_name=self_name,
                self_puuid="demo-puuid",
                source="demo",
                participants=parts,
            )
        )
    return matches
