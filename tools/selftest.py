"""不依赖 pytest 的自检脚本：python tools/selftest.py"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:  # 控制台是 GBK 时，✓ / ✗ 会炸，统一转成 UTF-8
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.models import BLUE, RED, Match, Participant  # noqa: E402
from app.sources.lcu import parse_match_detail  # noqa: E402
from app.stats import summarize, teammate_table, wilson  # noqa: E402
from app.store import Store  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name} {detail}")
        FAILS.append(name)


def _match(i: int, win: bool, me_dmg: int, me_taken: int, mates: list[str]) -> Match:
    parts = [
        Participant(name="Icarus", side=BLUE, slot=0, is_self=True,
                    damage_dealt=me_dmg, damage_taken=me_taken,
                    kills=5, deaths=5, assists=10),
    ]
    for s, n in enumerate(mates, start=1):
        parts.append(Participant(name=n, side=BLUE, slot=s, damage_dealt=1000))
    for s in range(5):
        parts.append(Participant(name=f"E{s}", side=RED, slot=s, damage_dealt=1000))
    return Match(
        match_id=f"t:{i}", created_at=1000 + i, duration_s=1800, mode="ARAM",
        win=win, self_side=BLUE, self_slot=0, self_name="Icarus", participants=parts,
    )


def test_wilson() -> None:
    print("wilson 置信区间（对照那张内鬼表的列）")
    lo, hi = wilson(83, 148)
    check("83/148 的 CI ≈ 48.0% ~ 63.8%", abs(lo * 100 - 48.0) < 0.1 and abs(hi * 100 - 63.8) < 0.1,
          f"得到 {lo*100:.1f}~{hi*100:.1f}")


def test_summary() -> None:
    print("统计口径")
    ms = [
        _match(1, True, 30000, 40000, ["A", "B"]),
        _match(2, True, 20000, 50000, ["A", "C"]),
        _match(3, False, 10000, 60000, ["B"]),
        _match(4, False, 20000, 30000, ["C"]),
    ]
    s = summarize(ms)
    check("场次/胜负", (s.games, s.wins, s.losses) == (4, 2, 2))
    check("胜率 50%", abs(s.win_rate - 0.5) < 1e-9)
    check("胜局输出总量 50000", s.dmg_win_total == 50000, str(s.dmg_win_total))
    check("胜局场均输出 25000", s.dmg_win_avg == 25000, str(s.dmg_win_avg))
    check("败局场均输出 15000", s.dmg_loss_avg == 15000, str(s.dmg_loss_avg))
    check("败局场均承伤 45000", s.taken_loss_avg == 45000, str(s.taken_loss_avg))
    check("场均时长 30 分钟", abs(s.avg_duration_min - 30) < 1e-6)


def test_teammates() -> None:
    print("队友聚合")
    ms = [
        _match(1, True, 1000, 1000, ["A"]),
        _match(2, True, 1000, 1000, ["A"]),
        _match(3, False, 1000, 1000, ["A"]),
    ]
    rows = {r.name: r for r in teammate_table(ms)}
    a = rows["A"]
    check("A 同队 3 场 2 胜", a.games == 3 and a.wins == 2)
    check("A 相对自己 +0.0（因为整体也是 2/3）", abs(a.delta) < 0.01, f"{a.delta}")


def test_lcu_parse() -> None:
    print("LCU 单场解析")
    detail = {
        "gameId": 123456,
        "gameCreation": 1_700_000_000_000,
        "gameDuration": 1830,
        "gameMode": "CLASSIC",
        "participantIdentities": [
            {"participantId": i + 1, "player": {"puuid": f"p{i}", "summonerName": f"玩家{i}"}}
            for i in range(10)
        ],
        "participants": [
            {
                "participantId": i + 1,
                "teamId": 100 if i < 5 else 200,
                "championId": 1,
                "stats": {
                    "win": i == 2,
                    "kills": i, "deaths": 2, "assists": 3,
                    "totalDamageDealtToChampions": 1000 * (i + 1),
                    "totalDamageTaken": 2000 * (i + 1),
                    "goldEarned": 12000, "totalMinionsKilled": 100, "visionScore": 20,
                },
            }
            for i in range(10)
        ],
    }
    m = parse_match_detail(detail, self_puuid="p2", champs={1: "安妮"})
    check("解析出 10 人", m is not None and len(m.participants) == 10)
    if m:
        check("我是 玩家2", m.self_name == "玩家2")
        check("我方 = 蓝方", m.self_side == BLUE)
        check("胜负取的是自己的 stats.win", m.win is True)
        check("时长 1830s", m.duration_s == 1830)
        check("创建时间按秒", m.created_at == 1_700_000_000)
        check("伤害/承伤映射", m.me.damage_dealt == 3000 and m.me.damage_taken == 6000)
        check("英雄名回填", m.me.champion == "安妮")
        check("队友不含自己", len(m.teammates) == 4)


def test_store() -> None:
    print("存储往返")
    td = ROOT / ".tmp" / "selftest-db"
    td.mkdir(parents=True, exist_ok=True)
    db = td / "t.db"
    if db.exists():
        db.unlink()
    st = Store(db)
    m = _match(9, True, 12345, 23456, ["X"])
    check("首次写入算新增", st.upsert(m) is True)
    check("重复写入不算新增", st.upsert(m) is False)
    back = st.all()
    check("读回 1 场", len(back) == 1)
    check("伤害保持不变", back[0].me.damage_dealt == 12345)
    check("队友名字没丢", back[0].teammates[0].name == "X")
    st.clear()
    check("清空生效", st.count() == 0)
    st.close()


def test_store_threads() -> None:
    """采集在 QThread 里跑，界面在主线程读——连接必须允许跨线程。"""
    print("存储跨线程")
    import threading

    td = ROOT / ".tmp" / "selftest-threads"
    td.mkdir(parents=True, exist_ok=True)
    db = td / "t.db"
    if db.exists():
        db.unlink()
    st = Store(db)
    errors: list[str] = []

    def writer(n: int) -> None:
        try:
            for i in range(20):
                st.upsert(_match(n * 100 + i, i % 2 == 0, 1000, 1000, ["A"]))
        except Exception as exc:  # noqa: BLE001
            errors.append(repr(exc))

    threads = [threading.Thread(target=writer, args=(k,)) for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("4 个线程各写 20 场，没有异常", not errors, str(errors[:1]))
    check("总共 80 场", st.count() == 80, str(st.count()))
    check("主线程仍能读", len(st.all()) == 80)
    st.close()


def main() -> int:
    for fn in (test_wilson, test_summary, test_teammates, test_lcu_parse, test_store, test_store_threads):
        fn()
        print()
    if FAILS:
        print(f"✗ {len(FAILS)} 项失败：{', '.join(FAILS)}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
