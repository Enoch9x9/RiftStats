"""统计引擎：胜率、输出/承伤聚合、队友维度对比。

所有函数都是纯函数，只吃 list[Match]，方便后面替换数据源或写测试。
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from .models import Match


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 95% 置信区间，和之前那张表用的是同一套算法。"""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - half), min(1.0, center + half))


@dataclass
class Summary:
    games: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    win_rate_ci: tuple[float, float] = (0.0, 1.0)

    # 输出
    dmg_total_all: int = 0
    dmg_win_total: int = 0
    dmg_win_avg: float = 0.0
    dmg_loss_avg: float = 0.0
    dmg_avg: float = 0.0
    dmg_per_min: float = 0.0

    # 承伤
    taken_win_avg: float = 0.0
    taken_loss_avg: float = 0.0
    taken_avg: float = 0.0

    # 队内占比 / 其他
    share_avg: float = 0.0
    share_win_avg: float = 0.0
    share_loss_avg: float = 0.0
    kda: float = 0.0
    avg_duration_min: float = 0.0
    total_duration_min: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def summarize(matches: list[Match], viewer: str | None = None) -> Summary:
    s = Summary()
    s.games = len(matches)
    if not s.games:
        return s

    def who(m: Match):
        return m.player_for(viewer)

    dmg_win = [who(m).damage_dealt for m in matches if m.win and who(m)]
    dmg_loss = [who(m).damage_dealt for m in matches if not m.win and who(m)]
    taken_win = [who(m).damage_taken for m in matches if m.win and who(m)]
    taken_loss = [who(m).damage_taken for m in matches if not m.win and who(m)]
    dmg_all = dmg_win + dmg_loss
    taken_all = taken_win + taken_loss

    s.wins = sum(1 for m in matches if m.win)
    s.losses = s.games - s.wins
    s.win_rate = s.wins / s.games
    s.win_rate_ci = wilson(s.wins, s.games)

    s.dmg_total_all = sum(dmg_all)
    s.dmg_win_total = sum(dmg_win)
    s.dmg_win_avg = sum(dmg_win) / len(dmg_win) if dmg_win else 0.0
    s.dmg_loss_avg = sum(dmg_loss) / len(dmg_loss) if dmg_loss else 0.0
    s.dmg_avg = sum(dmg_all) / len(dmg_all) if dmg_all else 0.0

    s.taken_win_avg = sum(taken_win) / len(taken_win) if taken_win else 0.0
    s.taken_loss_avg = sum(taken_loss) / len(taken_loss) if taken_loss else 0.0
    s.taken_avg = sum(taken_all) / len(taken_all) if taken_all else 0.0

    total_seconds = sum(max(m.duration_s, 60) for m in matches)
    s.total_duration_min = total_seconds / 60.0
    s.avg_duration_min = s.total_duration_min / s.games
    s.dmg_per_min = (s.dmg_total_all / s.total_duration_min) if s.total_duration_min else 0.0

    shares = [sh for sh in (m.share_for(who(m)) for m in matches) if sh]
    s.share_avg = sum(shares) / len(shares) if shares else 0.0

    shares_win = [sh for m in matches if m.win for sh in [m.share_for(who(m))] if sh]
    shares_loss = [sh for m in matches if not m.win for sh in [m.share_for(who(m))] if sh]
    s.share_win_avg = sum(shares_win) / len(shares_win) if shares_win else 0.0
    s.share_loss_avg = sum(shares_loss) / len(shares_loss) if shares_loss else 0.0

    ks = sum(who(m).kills for m in matches if who(m))
    ds = sum(who(m).deaths for m in matches if who(m))
    as_ = sum(who(m).assists for m in matches if who(m))
    s.kda = (ks + as_) / max(ds, 1)
    return s


@dataclass
class TeammateRow:
    name: str
    games: int
    wins: int
    win_rate: float
    ci: tuple[float, float]
    delta: float  # 相对自己整体胜率，单位：点
    dmg_avg: float = 0.0
    taken_avg: float = 0.0
    share_avg: float = 0.0
    last_played: int = 0
    is_friend: bool = False

    @property
    def ci_text(self) -> str:
        return f"{self.ci[0]*100:.1f}% ~ {self.ci[1]*100:.1f}%"


def teammate_table(
    matches: list[Match],
    min_games: int = 1,
    friend_names: set[str] | None = None,
    viewer: str | None = None,
) -> list[TeammateRow]:
    """按队友聚合。friend_names 里的人是"好友"，其余算路人。"""
    friends = {n.strip().lower() for n in (friend_names or set())}
    overall = summarize(matches, viewer=viewer)
    base = overall.win_rate

    buckets: dict[str, list[Match]] = defaultdict(list)
    for m in matches:
        # 视角玩家的队友，不是"我"的队友——否则换视角时看不到原视角玩家
        for name in {p.name for p in m.teammates_of(viewer) if p.name}:
            buckets[name].append(m)

    def who(m: Match):
        return m.player_for(viewer)

    rows: list[TeammateRow] = []
    for name, ms in buckets.items():
        if len(ms) < min_games:
            continue
        wins = sum(1 for m in ms if m.win)
        rate = wins / len(ms)
        dmg = [who(m).damage_dealt for m in ms if who(m)]
        taken = [who(m).damage_taken for m in ms if who(m)]
        shares = [m.share_for(who(m)) for m in ms if m.share_for(who(m))]
        rows.append(
            TeammateRow(
                name=name,
                games=len(ms),
                wins=wins,
                win_rate=rate,
                ci=wilson(wins, len(ms)),
                delta=(rate - base) * 100,
                dmg_avg=sum(dmg) / len(dmg) if dmg else 0.0,
                taken_avg=sum(taken) / len(taken) if taken else 0.0,
                share_avg=sum(shares) / len(shares) if shares else 0.0,
                last_played=max(m.created_at for m in ms),
                is_friend=name.strip().lower() in friends,
            )
        )
    rows.sort(key=lambda r: (-r.games, r.name))
    return rows


def teammate_effect(rows: list[TeammateRow], min_games: int = 10) -> TeammateRow | None:
    """样本达标里胜率最高的那个，用来做"谁最像内鬼/福星"的结论句。"""
    eligible = [r for r in rows if r.games >= min_games]
    return max(eligible, key=lambda r: r.win_rate) if eligible else None


@dataclass
class ChampionRow:
    name: str
    games: int
    wins: int
    win_rate: float
    dmg_avg: float = 0.0
    kda: float = 0.0

    @property
    def ci_text(self) -> str:
        return "%.1f%% ~ %.1f%%" % (wilson(self.wins, self.games)[0] * 100,
                                     wilson(self.wins, self.games)[1] * 100)


def champion_table(matches: list[Match], viewer: str | None = None) -> list[ChampionRow]:
    """按我用的英雄聚合。"""
    buckets: dict[str, list[Match]] = defaultdict(list)
    for m in matches:
        me = m.player_for(viewer)
        if me and me.champion:
            buckets[me.champion].append(m)

    rows: list[ChampionRow] = []
    for name, ms in buckets.items():
        wins = sum(1 for m in ms if m.win)
        dmg = [m.me.damage_dealt for m in ms if m.me]
        ks = sum(m.me.kills for m in ms if m.me)
        ds = sum(m.me.deaths for m in ms if m.me)
        as_ = sum(m.me.assists for m in ms if m.me)
        rows.append(
            ChampionRow(
                name=name,
                games=len(ms),
                wins=wins,
                win_rate=wins / len(ms),
                dmg_avg=sum(dmg) / len(dmg) if dmg else 0.0,
                kda=(ks + as_) / max(ds, 1),
            )
        )
    rows.sort(key=lambda r: (-r.games, r.name))
    return rows


def best_and_worst_champion(
    matches: list[Match], min_games: int = 10, viewer: str | None = None
) -> tuple[ChampionRow | None, ChampionRow | None]:
    """胜率最高 / 最低的英雄。样本不够时逐级放宽阈值。"""
    for threshold in (min_games, 5, 3, 2, 1):
        rows = [r for r in champion_table(matches, viewer=viewer) if r.games >= threshold]
        if len(rows) >= 2:
            best = max(rows, key=lambda r: (r.win_rate, r.games))
            worst = min(rows, key=lambda r: (r.win_rate, -r.games))
            return best, worst
        if len(rows) == 1:
            return rows[0], None
    return None, None


@dataclass
class ChampAdvice:
    """英雄推荐用的一行。"""

    name: str
    games: int
    wins: int
    win_rate: float
    ci: tuple[float, float]
    pick_rate: float
    dmg_avg: float
    dmg_win_avg: float
    dmg_loss_avg: float
    taken_avg: float
    kda: float
    score: float
    grade: str

    @property
    def ci_text(self) -> str:
        return f"{self.ci[0]*100:.1f}% ~ {self.ci[1]*100:.1f}%"


def _corr(a: list[float], b: list[float]) -> float:
    n = len(a)
    if n < 2:
        return 0.0
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return 0.0
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


# 经验权重：胜率占 45%，剩下 50% 给输出/承伤/KDA，10% 给选取率
PRIOR_WEIGHTS = {"win_rate": 0.45, "dmg": 0.20, "taken": 0.10, "kda": 0.20, "pick": 0.10}


@dataclass
class GearRow:
    """一件装备 / 一个强化，在你这些对局里的表现。"""

    key: int
    name: str
    games: int
    wins: int
    win_rate: float
    delta: float
    share: float


def gear_table(
    matches: list[Match], viewer: str | None = None, champion: str | None = None,
    min_games: int = 1,
) -> tuple[list[GearRow], list[GearRow], int]:
    """统计装备与强化。返回 (装备行, 强化行, 参与统计的对局数)。"""
    from .catalog import augment_name, item_name

    picked: list[Match] = []
    for m in matches:
        p = m.player_for(viewer)
        if not p:
            continue
        if champion and p.champion != champion:
            continue
        picked.append(m)

    if not picked:
        return [], [], 0

    base = sum(1 for m in picked if m.win) / len(picked)

    item_bucket: dict[int, list[Match]] = defaultdict(list)
    aug_bucket: dict[int, list[Match]] = defaultdict(list)
    for m in picked:
        p = m.player_for(viewer)
        for iid in set(p.items):
            item_bucket[iid].append(m)
        for aid in set(p.augments):
            aug_bucket[aid].append(m)

    def build(bucket: dict[int, list[Match]], namer, offset: int) -> list[GearRow]:
        rows: list[GearRow] = []
        for key, ms in bucket.items():
            if len(ms) < min_games:
                continue
            wins = sum(1 for m in ms if m.win)
            rate = wins / len(ms)
            rows.append(
                GearRow(
                    key=key + offset,
                    name=namer(key),
                    games=len(ms),
                    wins=wins,
                    win_rate=rate,
                    delta=(rate - base) * 100,
                    share=len(ms) / len(picked),
                )
            )
        rows.sort(key=lambda r: (-r.win_rate, -r.games))
        return rows

    return (
        build(item_bucket, item_name, 0),
        build(aug_bucket, augment_name, 100000),
        len(picked),
    )


# ---------------------------------------------------------------------------
# 近期评价
# ---------------------------------------------------------------------------

_QUIPS = {
    "S": [
        "最近 {n} 场你这是把对手当练桩机用了，场均 {dpm}，比你自己平时的数据高出 {diff}%。",
        "输出拉满，节奏还在手上。场均 {dpm}、占比 {share}%，这波不是运气，是手感在线。",
        "别急着谦虚，{n} 场打出这个量，你近期确实在状态里。",
    ],
    "A": [
        "打得不错，场均 {dpm} 不算虚，就是还差一口气没到离谱的程度。",
        "高于你自己的平均线 {diff}%，说明最近手感偏热，别断，趁热多打几场。",
        "输出稳，节奏也稳，属于‘不拖后腿还带点输出’的那种。",
    ],
    "B": [
        "稳如老树皮：场均 {dpm}，跟你平时一模一样，赢了不靠你，输了也不怪你。",
        "中规中矩，{n} 场里输出基本贴着均值走，属于队伍里的背景板但至少不塌。",
        "不好不坏，胜率 {wr}%。这段时间你在游戏里的存在感，跟家里的路由器差不多——有用，但没人想起。",
    ],
    "C": [
        "场均 {dpm}，比你平时低了 {diff}%。要么在划水，要么把把被针对，反正看着不太像在认真玩。",
        "输出掉到这个程度，赢的局也不是你赢的。承认吧，最近是有点混。",
        "这 {n} 场里你的主要贡献可能是帮队友分摊了一点仇恨值。",
    ],
    "D": [
        "场均 {dpm}，比平时少 {diff}%。这段数据的观赏性大于实用性，建议先休息一下再上。",
        "老实说，这 {n} 场的输出不足以支撑任何战术讨论，先别管段位，把手感找回来。",
        "数据不好看不是问题，问题是你可能自己也感觉到了。歇一局，喝口水，别硬打。",
    ],
}


@dataclass
class RecentReport:
    games: int
    wins: int
    win_rate: float
    score: float
    grade: str
    comment: str
    dpm: float
    dpm_base: float
    share: float
    share_base: float
    kda: float
    kda_base: float
    mode_note: str


def recent_report(
    matches: list[Match], viewer: str | None = None, window: int = 20
) -> RecentReport | None:
    """最近 window 场的评价。输出占 50%，其余是占比 / KDA / 胜率。

    基线取"同一批对局里，你自己"的长期平均，所以这是"跟你自己比"，不是跟路人比。
    """
    if not matches:
        return None
    picked = matches[:window]
    if not picked:
        return None

    def metrics(ms: list[Match]) -> tuple[float, float, float, int]:
        dpm_sum = 0.0
        share_sum = 0.0
        ks = ds = as_ = 0
        wins = 0
        used = 0
        for m in ms:
            p = m.player_for(viewer)
            if not p:
                continue
            used += 1
            mins = max(m.duration_s, 60) / 60.0
            dpm_sum += p.damage_dealt / mins
            share_sum += m.share_for(p)
            ks += p.kills
            ds += p.deaths
            as_ += p.assists
            if m.win:
                wins += 1
        if not used:
            return 0.0, 0.0, 0.0, 0
        return (
            dpm_sum / used,
            share_sum / used,
            (ks + as_) / max(ds, 1),
            wins,
        )

    dpm, share, kda, wins = metrics(picked)
    b_dpm, b_share, b_kda, _ = metrics(matches)
    if b_dpm <= 0:
        b_dpm = dpm or 1.0
    if b_share <= 0:
        b_share = share or 0.01
    if b_kda <= 0:
        b_kda = kda or 1.0

    wr = wins / len(picked)
    wr_base = sum(1 for m in matches if m.win) / len(matches)

    def ratio(now: float, base: float, cap: float = 1.6) -> float:
        if base <= 0:
            return 1.0
        return max(0.0, min(cap, now / base))

    r_dpm = ratio(dpm, b_dpm)
    r_share = ratio(share, b_share)
    r_kda = ratio(kda, b_kda)
    r_wr = ratio(wr, wr_base) if wr_base > 0 else 1.0

    # 加权比值 1.0 = 跟自己的长期平均持平 = 60 分（B）
    mixed = 0.50 * r_dpm + 0.25 * r_share + 0.15 * r_kda + 0.10 * r_wr
    score = 60.0 + (mixed - 1.0) * 100.0
    score = max(0.0, min(100.0, score))

    if score >= 85:
        grade = "S"
    elif score >= 70:
        grade = "A"
    elif score >= 55:
        grade = "B"
    elif score >= 40:
        grade = "C"
    else:
        grade = "D"

    diff = abs(r_dpm - 1.0) * 100
    pool = _QUIPS[grade]
    template = pool[int(score) % len(pool)]
    comment = template.format(
        n=len(picked), dpm=f"{dpm:,.0f}", diff=f"{diff:.0f}", share=f"{share*100:.0f}",
        wr=f"{wr*100:.0f}",
    )

    aram = sum(1 for m in picked if m.mode in ("KIWI", "KIWI_JADE", "ARAM"))
    mode_note = ""
    if aram >= len(picked) * 0.6:
        mode_note = "近%s场以海克斯大乱斗为主，按乱斗口径评" % len(picked)

    return RecentReport(
        games=len(picked),
        wins=wins,
        win_rate=wr,
        score=score,
        grade=grade,
        comment=comment,
        dpm=dpm,
        dpm_base=b_dpm,
        share=share,
        share_base=b_share,
        kda=kda,
        kda_base=b_kda,
        mode_note=mode_note,
    )


def feature_weights(matches: list[Match], viewer: str | None = None) -> dict[str, float]:
    """用你自己的对局数据决定"主要看什么"。

    做法：算每分钟伤害 / 每分钟承伤 / KDA 与"这一局赢没赢"的相关性，
    相关性越强的项权重越高。胜率本身是目标不算特征，固定占 40%；
    选取率是英雄层面的属性，没有逐局相关性，固定 10%。

    样本太少（<60 场）时退回经验权重，免得拟合出一堆噪声。
    """
    rows = []
    for m in matches:
        me = m.player_for(viewer)
        if not me:
            continue
        mins = max(m.duration_s, 60) / 60.0
        rows.append(
            (
                1.0 if m.win else 0.0,
                me.damage_dealt / mins,
                me.damage_taken / mins,
                (me.kills + me.assists) / max(me.deaths, 1),
            )
        )
    if len(rows) < 60:
        return dict(PRIOR_WEIGHTS)

    y = [r[0] for r in rows]
    r_dmg = abs(_corr([r[1] for r in rows], y))
    r_taken = abs(_corr([r[2] for r in rows], y))
    r_kda = abs(_corr([r[3] for r in rows], y))
    total = r_dmg + r_taken + r_kda
    if total <= 1e-6:
        return dict(PRIOR_WEIGHTS)

    # 数据和经验各占一半：纯按相关性分，会把"KDA 刷得高但胜率不到五成"的英雄
    # 推到前面，所以留一半给经验权重压住。
    budget = 0.50
    out = {"win_rate": 0.45, "pick": 0.10}
    for key, r, prior in (
        ("dmg", r_dmg, PRIOR_WEIGHTS["dmg"]),
        ("taken", r_taken, PRIOR_WEIGHTS["taken"]),
        ("kda", r_kda, PRIOR_WEIGHTS["kda"]),
    ):
        out[key] = 0.5 * (budget * r / total) + 0.5 * prior
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def champion_advice(
    matches: list[Match],
    min_games: int = 5,
    weights: dict[str, float] | None = None,
    viewer: str | None = None,
) -> list[ChampAdvice]:
    """英雄推荐：胜率（保守下界）+ 输出 + 承伤 + KDA + 选取率。

    评分 0~100：五项各取"在你自己所有英雄里的百分位"，再按权重加总。

    权重不是拍脑袋定的：`feature_weights()` 会算每分钟伤害 / 每分钟承伤 / KDA
    与"这局赢没赢"的相关性，相关性强的项权重就高。在你现在的数据里 KDA 最相关，
    所以 KDA 的权重会被抬高、输出被压低。
    """
    if not matches:
        return []
    overall = summarize(matches, viewer=viewer)
    base_dmg = overall.dmg_avg or 1.0
    base_taken = overall.taken_avg or 1.0
    base_kda = overall.kda or 1.0
    total = len(matches)

    buckets: dict[str, list[Match]] = defaultdict(list)
    for m in matches:
        me = m.player_for(viewer)
        if me and me.champion:
            buckets[me.champion].append(m)

    max_games = max((len(v) for v in buckets.values()), default=1)
    w = weights or feature_weights(matches)
    raw: list[dict] = []
    for name, ms in buckets.items():
        wins = sum(1 for m in ms if m.win)
        dmg = [m.me.damage_dealt for m in ms if m.me]
        dmg_win = [m.me.damage_dealt for m in ms if m.win and m.me]
        dmg_loss = [m.me.damage_dealt for m in ms if not m.win and m.me]
        taken = [m.me.damage_taken for m in ms if m.me]
        ks = sum(m.me.kills for m in ms if m.me)
        ds = sum(m.me.deaths for m in ms if m.me)
        as_ = sum(m.me.assists for m in ms if m.me)

        avg_dmg = sum(dmg) / len(dmg) if dmg else 0.0
        avg_taken = sum(taken) / len(taken) if taken else 0.0
        kda = (ks + as_) / max(ds, 1)
        lo, _hi = wilson(wins, len(ms))

        raw.append(
            dict(
                name=name,
                games=len(ms),
                wins=wins,
                win_rate=wins / len(ms),
                ci=wilson(wins, len(ms)),
                pick_rate=len(ms) / total,
                dmg_avg=avg_dmg,
                dmg_win_avg=sum(dmg_win) / len(dmg_win) if dmg_win else 0.0,
                dmg_loss_avg=sum(dmg_loss) / len(dmg_loss) if dmg_loss else 0.0,
                taken_avg=avg_taken,
                kda=kda,
                wlb=lo,
            )
        )

    def pct(value_of, eligible_key: str) -> dict[str, float]:
        """在"样本达标"的英雄里算百分位，0~1。"""
        pool = [r for r in raw if r["games"] >= min_games] or raw
        vals = sorted(value_of(r) for r in pool)
        n = len(vals)
        out: dict[str, float] = {}
        for r in raw:
            v = value_of(r)
            idx = sum(1 for x in vals if x <= v)
            out[r[eligible_key]] = (idx - 0.5) / n if n else 0.5
        return out

    p_wr = pct(lambda r: r["wlb"], "name")
    p_dmg = pct(lambda r: r["dmg_avg"], "name")
    p_taken = pct(lambda r: r["taken_avg"], "name")
    p_kda = pct(lambda r: r["kda"], "name")
    p_pick = pct(lambda r: r["games"], "name")

    rows: list[ChampAdvice] = []
    for r in raw:
        score = 100 * (
            w["win_rate"] * p_wr[r["name"]]
            + w["dmg"] * p_dmg[r["name"]]
            + w["taken"] * p_taken[r["name"]]
            + w["kda"] * p_kda[r["name"]]
            + w["pick"] * p_pick[r["name"]]
        )
        grade = "样本不足" if r["games"] < min_games else "C"
        rows.append(
            ChampAdvice(
                name=r["name"],
                games=r["games"],
                wins=r["wins"],
                win_rate=r["win_rate"],
                ci=r["ci"],
                pick_rate=r["pick_rate"],
                dmg_avg=r["dmg_avg"],
                dmg_win_avg=r["dmg_win_avg"],
                dmg_loss_avg=r["dmg_loss_avg"],
                taken_avg=r["taken_avg"],
                kda=r["kda"],
                score=round(score, 1),
                grade=grade,
            )
        )
    rows.sort(key=lambda r: (-r.score, -r.games))

    # 等级按"达标英雄里的排名"给，保证不管样本多少都分得出高低：
    # 前 15% = S，接下来 25% = A，再 30% = B，剩下 C
    eligible = [r for r in rows if r.grade != "样本不足"]
    n = len(eligible)
    for i, r in enumerate(eligible):
        frac = i / n if n else 0
        r.grade = "S" if frac < 0.15 else "A" if frac < 0.40 else "B" if frac < 0.70 else "C"
    return rows


# ---------------------------------------------------------------------------
# 单局伤害评分 / 经济贡献
# ---------------------------------------------------------------------------
# 伤害评分口径：以"每分钟伤害 + 队内输出占比 + 伤害转化率 + 生存"四项加权，
# 全部用绝对刻度（阈值取自 1300 场真实数据的 p50 / p90），所以不同版本、
# 不同对局之间可以直接比较。
SCORE_WEIGHTS = {"dpm": 0.35, "share": 0.30, "conv": 0.20, "survive": 0.15}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def player_score(p: "Participant", team_damage: int, duration_s: int) -> float:
    """0~100 的单局伤害评分。

    - 每分钟伤害：1862(p50)→约 50 分，3422(p90)→约 98 分
    - 队内输出占比：10% → 0 分，30% → 100 分
    - 伤害转化率（伤害/金币）：1.2 → 0 分，3.6 → 100 分
    - 生存：每 10 分钟死亡 ≤4 次满分，12 次降到 20 分
    另外：人头多但转化率低 / 占比低，额外扣分——这就是"人头虚高"。
    """
    minutes = max(duration_s, 60) / 60.0
    dpm = p.damage_dealt / minutes
    share = p.damage_dealt / team_damage if team_damage else 0.0
    conv = p.damage_dealt / p.gold if p.gold else 0.0
    deaths10 = p.deaths / minutes * 10

    dpm_s = _clamp(dpm / 3500 * 100)
    share_s = _clamp((share - 0.10) / 0.20 * 100)
    conv_s = _clamp((conv - 1.2) / 2.4 * 100)
    surv_s = _clamp(100 - max(0.0, deaths10 - 4) * 10)

    score = (
        dpm_s * SCORE_WEIGHTS["dpm"]
        + share_s * SCORE_WEIGHTS["share"]
        + conv_s * SCORE_WEIGHTS["conv"]
        + surv_s * SCORE_WEIGHTS["survive"]
    )

    # 人头虚高惩罚
    if p.kills >= 6 and conv < 1.8:
        score -= 12
    if p.kills >= 10 and share < 0.15:
        score -= 10
    if p.kills >= 6 and p.deaths >= 8 and conv < 1.6:
        score -= 6  # 又送又刷
    return round(_clamp(score), 1)


def match_scores(match: Match) -> dict[int, float]:
    """这一局 10 个人各自的伤害评分，键是 participant 在列表里的下标。"""
    out: dict[int, float] = {}
    for side in (100, 200):
        team = match.team(side)
        total = sum(p.damage_dealt for p in team)
        for p in team:
            idx = match.participants.index(p)
            out[idx] = player_score(p, total, match.duration_s)
    return out


def match_contributions(match: Match) -> dict[int, float]:
    """团队贡献率：个人伤害评分 / 本队伤害评分之和，0~1。

    每队 5 人，平均就是 20%。用它比"输出占比"更全面，因为伤害评分里已经含了
    转化率、生存和人头虚高惩罚。
    """
    scores = match_scores(match)
    out: dict[int, float] = {}
    for side in (100, 200):
        idxs = [i for i, p in enumerate(match.participants) if p.side == side]
        total = sum(scores.get(i, 0.0) for i in idxs) or 1.0
        for i in idxs:
            out[i] = scores.get(i, 0.0) / total
    return out


def gold_given(p: "Participant") -> float:
    """这个人死一次送出去多少金币（估算）。

    基础 300；击杀越多，对方拿到的赏金越高（封顶再加 300）。
    人头多、死得也多的人，这个数字会很大——这就是"送经济"。
    """
    per_death = 300 + min(300, 40 * p.kills)
    return per_death * p.deaths


def assist_share(p: "Participant", team: list["Participant"]) -> float:
    total = sum(x.assists for x in team)
    return p.assists / total if total else 0.0


def feed_share(p: "Participant", team: list["Participant"]) -> float:
    """送经济占比：本队 5 人里，他一个人送出去的比例（五个人加起来 = 100%）。"""
    total = sum(gold_given(x) for x in team)
    return gold_given(p) / total if total else 0.0


def feed_vs_enemy(p: "Participant", enemy_team: list["Participant"]) -> float:
    """他送的金币占敌方总经济的比例（分母是敌方全部收入，所以通常只有个位数）。"""
    enemy_gold = sum(x.gold for x in enemy_team)
    return gold_given(p) / enemy_gold if enemy_gold else 0.0


def recent_scores(
    matches: list[Match], limit: int, viewer: str | None = None
) -> list[tuple[Match, float]]:
    """最近 limit 场里，视角玩家的伤害评分（matches 需按时间倒序）。"""
    out: list[tuple[Match, float]] = []
    for m in matches[:limit]:
        me = m.player_for(viewer)
        if not me:
            continue
        out.append((m, player_score(me, m.team_damage, m.duration_s)))
    return out


def win_streak(matches: list[Match]) -> int:
    """当前连胜（负数为连败）。matches 需按时间倒序。"""
    streak = 0
    for m in matches:
        if streak == 0:
            streak = 1 if m.win else -1
            continue
        if m.win and streak > 0:
            streak += 1
        elif not m.win and streak < 0:
            streak -= 1
        else:
            break
    return streak
