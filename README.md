# RiftStats · 峡谷数据台

一个跑在 Windows 上的英雄联盟对局数据分析工具。Python + Qt6（PySide6），
纯本地、不联网、数据存在自己的硬盘里。

v0.1 的目标很朴素：**先把"拿到数据"和"看得懂数据"这两件事做通**，
截图识别（OCR）留到 v0.2 接。

---

## 一、现在能做什么

| 功能 | 状态 |
|---|---|
| 客户端直连，自动拉取你自己的对局记录（不需要截图、不需要 API key） | ✅ 可用 |
| 单场手动录入（左侧看截图，右侧 10 行表格，按行序填） | ✅ 可用 |
| SQLite 存档 / 去重 / 删除 / 导出 CSV | ✅ 可用 |
| 总览：胜率+置信区间、场均输出、胜局输出总量、胜局场均输出、败局场均输出/承伤 | ✅ 可用 |
| 队友维度：同队场次、胜率、95% CI、相对自己的差值、场均输出/承伤 | ✅ 可用 |
| 截图 OCR 自动识别 | ⏳ v0.2 |
| 好友关系标记、多赛季对比、按英雄/位置拆分 | ⏳ 后续 |

第一次启动如果数据库是空的，会自动塞 48 场**演示数据**，左侧会明确标
"当前全是演示数据"。点「导入数据 → 清空演示数据」即可清掉。

## 二、怎么跑

```powershell
# 开发模式（已经装好依赖）
.\run.ps1

# 或者手动
$env:PYTHONPATH = ".\libs"
python launch.py
```

依赖放在 `libs/`（不是虚拟环境，是 `pip install --target` 的效果），
因为本机 pip 解包被拦截过，`tools/wheel_fetch.py` 用 urllib + zipfile
直接把 wheel 解开到 `libs/`，等价于装好了。

打包成单个 exe：

```powershell
.\build_exe.ps1        # 产物在 dist\RiftStats.exe
```

## 三、数据从哪来（重点）

三条路，按推荐程度排：

### 1. 客户端本地接口（LCU）—— 首选

游戏客户端启动后会在安装目录写一个 `lockfile`：

```
LeagueClient:12345:54321:password:https
     进程名     PID   端口    密码   协议
```

用 Basic 认证（用户名固定 `riot`）访问 `https://127.0.0.1:<端口>` 就能读到自己
的全部对局记录。**不需要 API key，不需要截图，10 个玩家的完整数据都有。**

用到的节点：

| 接口 | 用途 |
|---|---|
| `GET /lol-summoner/v1/current-summoner` | 我是谁（puuid） |
| `GET /lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=19` | 最近 20 场 ID |
| `GET /lol-match-history/v1/games/{gameId}` | 单场 10 人明细 |
| `GET /lol-game-data/assets/v1/champion-summary.json` | 英雄 ID → 名字 |
| `GET /lol-gameflow/v1/gameflow-phase` | 客户端当前状态（闲置/选人/对局中） |

单场明细里每个 participant 的 `stats` 就有
`totalDamageDealtToChampions`（对英雄伤害）、`totalDamageTaken`（承伤）、
`kills/deaths/assists`、`goldEarned`、`visionScore`。
—— 正好是那张"内鬼表"需要的全部字段，而且**不再有 6 局、4 局这种样本**。

lockfile 查找顺序：`RIFTSTATS_LOCKFILE` 环境变量 → 运行中的 `LeagueClientUx.exe`
命令行里的 `--install-directory` → 注册表（`HKCU\SOFTWARE\Tencent\LOL` 的
`InstallPath`，国服走这条）→ 常见安装路径 → 各盘两层结构扫描。

### ⚠️ 国服实测：lockfile 根本不写

腾讯版（TCLS/WeGame 布局，`D:\League of Legends\英雄联盟\`）实测 **lockfile 是
0 字节**，停留在几个月前，客户端却在正常提供服务。端口和密码只能从客户端日志里拿：

```
D:\...\英雄联盟\LeagueClient\2026-11-17T10-26-16_..._LeagueClientUx.log
  ... https://riot:M2WdgHBEIFEIAQqWKmPUsA@127.0.0.1:56439/index.html
```

所以发现逻辑加了一级：lockfile 全部失败时，扫最近 6 个 `LeagueClientUx*.log`，
用正则捞出 `https://riot:<password>@127.0.0.1:<port>`，再拿端口做一次带认证的
`/riotclient/region-locale` 校验（防止连到别的程序）。这条路线在本机实测可用。

### ⚠️ 对局历史的硬限制：一次只有 20 场

`/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=&endIndex=`
看起来能分页，实际上 **`begIndex` 被无视**：本地只缓存一页 20 场，缓存窗口跟着
客户端 UI 走。实测过：

- 8 种参数名（`begIndex` / `beginIndex` / `startIndex` / `offset` / `page` …），只有 `begIndex` 不报 400，但内容不变
- 空闲 60 秒不会自动刷新回最新页
- `POST` 刷新 → 405 Method Not Allowed
- v2 / v3 matchlist → 404
- `/swagger/v3/openapi.json` → 404

**但 `/lol-match-history/v1/games/{gameId}` 对任意老对局都能拉。** 问题只剩 gameId
从哪来：gameId 是全区顺序号（4 天涨约 1000 万），扫不出来。

所以唯一可行的多条获取方式是**跟着 UI 翻页抓**：

```
客户端「对局记录」每往下滚一页 → 本地缓存窗口换一页 → 我们每 1.2 秒轮询一次
→ 窗口首场 id 变化就说明翻页了 → 把这一页 20 场全部抓下来入库
```

代码在 `lcu.harvest()`，界面上是「深度采集（跟滚 4 分钟）」。滚 10 页 = 200 场。

### ✅ 但日志里藏着每一场的 gameId

客户端日志（`LeagueClient\*.log`、`LeagueClient-tracing.json`、`Riot Client\log`）
会打印打过的每一场对局的 id，一个月的日志能凑出近两百个候选。配合
`/lol-match-history/v1/games/{gameId}` 逐条反查，就能把**几个月前的对局全部找回来**。

实测：527 个日志文件 → 190 个候选 id → 验证出 **171 场真实对局，时间跨度 8/15 ~ 11/16**。
候选里混着别人的 id 和误报，所以每条都要反查一次，`parse_match_detail` 返回 None
就丢掉（本机命中率约 90%）。

界面上是「从本地日志恢复历史」，代码在 `lcu.harvest_from_logs()`。默认跳过库里已有的，
所以第二次点只花几秒。

### 2. Riot 官方 API（match-v5）—— 国服基本用不上

`https://<region>.api.riotgames.com/lol/match/v5/matches/{matchId}` 能拿到
同样的 10 人数据，字段更规范。但：① 需要开发者 key（免费 key 24 小时过期）；
② **国服由腾讯独立运营，不在 Riot 官方 API 的覆盖区域内**，国服账号拿不到数据。

所以对国服玩家来说，LCU 是唯一靠谱的自动方案。

### 3. 截图识别 —— 兜底

没有客户端（比如帮朋友算、看别人的图）时才需要。v0.1 先把表格和录入流程做好，
v0.2 接 RapidOCR（离线中文+数字，模型随包分发，不联网）：
按队伍固定行高切格 → 数字白名单识别 → 结果灌进可编辑表格 → 人核对一遍再入库。

> 为什么不做成纯自动？因为计分板和"图表"是两张图（图二是 KDA/金币，图一才是伤害），
> 必须按行序合并；数字识别错一位（17,361 → 17,861）会让所有统计悄悄失真，
> 留一步人工确认反而更快。

## 四、统计口径（别和插件那张表混）
| 指标 | 定义 |
|---|---|
| 胜率 | 胜场 / 总场次，附 Wilson 95% 置信区间 |
| 场均输出 | 对英雄伤害总和 / 场次；另给"每分钟伤害" |
| 胜局输出总量 | 所有获胜局的对英雄伤害之和 |
| 胜局/败局场均输出 | 分开算，避免"赢得快所以伤害低"被平均掉 |
| 败局场均承伤 | 输的局平均挨了多少伤害 |
| 队内输出占比 | 自己输出 / 我方队伍总输出，反映"是不是靠你打" |
| 相对自己 | 与某人同队时的胜率 − 自己的整体胜率（单位：百分点） |

置信区间用 Wilson，和之前那张表用的是同一套算法，方便对照。

### 单局伤害评分（0~100）

四项加权，全部是绝对刻度（阈值取自 1300 场真实数据的 p50 / p90）：

| 项 | 权重 | 换算 |
|---|---|---|
| 每分钟伤害 | 35% | 3500/分 → 100 分 |
| 队内输出占比 | 30% | 10% → 0 分，30% → 100 分 |
| 伤害转化率（伤害/金币） | 20% | 1.2 → 0 分，3.6 → 100 分 |
| 生存（每 10 分钟死亡） | 15% | ≤4 次满分，12 次 → 20 分 |

再加两条惩罚，专门治"人头虚高"：击杀 ≥6 且转化率 <1.8 扣 12 分；击杀 ≥10 且队内占比 <15% 再扣 10 分。

### 经济贡献两个比率

- **助攻占比** = 该玩家助攻 / 本队总助攻（5 人相加 = 100%）
- **送经济占比** = 该玩家送出金币 / 本队 5 人送出金币之和（5 人相加 = 100%），其中
  每次死亡按 `300 + min(300, 40 × 击杀数)` 估算（人头越多，赏金越高，死一次越亏）。
  单元格的悬浮提示里另有一个"占敌方总经济 x%"，分母是敌方全部收入，所以通常只有个位数。


### 英雄推荐

新页面「英雄推荐」把"该练谁"变成有依据的结论。评分是**五项在本账号所有英雄里的百分位**加权：

| 项 | 权重 | 说明 |
|---|---|---|
| 胜率 | 45% | 用 Wilson 95% 置信下界，小样本自动被压低 |
| 场均输出 | 25% | |
| 场均承伤 | 10% | |
| KDA | 10% | |
| 选取率 | 10% | 越常选，熟练度越可信 |

等级按达标英雄里的排名给：前 15% = S，接着 25% = A，再 30% = B，其余 C。
场次不够的一律标「样本不足」，不参与推荐（默认门槛 8 场，可调 3/5/8/10/15）。

表里同时给出**胜局输出 vs 败局输出**——同一个英雄你赢的时候打多少、输的时候掉多少，比单看一个场均数字有用。


### 近期评价（最近 20 场）

总览页顶部有一块**评级 + 评语**，只看最近 20 场，以**输出**为主要口径：

| 项 | 权重 |
|---|---|
| 每分钟伤害 | 50% |
| 队内输出占比 | 25% |
| KDA | 15% |
| 胜率 | 10% |

比值 1.0（跟自己的长期平均持平）= 60 分 = B。S ≥ 85、A ≥ 70、B ≥ 55、C ≥ 40、D 以下。
评语按档位生成，会带上你这一段的真实数字，风格偏毒舌——介意的把 `stats.py` 里 `_QUIPS` 改掉就行。

海克斯大乱斗占多数时，标题会标注"按乱斗口径评"。

## 五、目录结构

```
riftstats/
├── launch.py          # 启动入口（源码运行 + 打包都用它）
├── run.ps1            # 开发模式一键启动
├── build_exe.ps1      # PyInstaller 打包
├── app/
│   ├── models.py      # Match / Participant 数据模型
│   ├── store.py       # SQLite 存档（便携模式，数据在程序旁边的 data/）
│   ├── stats.py       # 统计引擎（纯函数，可单测）
│   ├── sources/
│   │   ├── lcu.py     # 客户端直连
│   │   └── demo.py    # 演示数据
│   └── ui/
│       ├── main_window.py / dashboard.py / matches.py
│       ├── teammates.py / importer.py / image_dialog.py
│       ├── widgets.py # KPI 卡片、图表、手绘条形榜单
│       └── theme.py   # 深海军蓝 + 海克斯金
├── tools/
│   ├── wheel_fetch.py # 不用 pip 也能装依赖
│   └── shot.py        # 离屏截图，检查排版
├── libs/              # 依赖（PySide6）
└── data/              # riftstats.db
```

## 六、下一步

1. **OCR**：`sources/ocr.py` + `ImageImportDialog.fill_from_rows()` 已经留好接口。
2. **好友标记**：从 `GET /lol-chat/v1/friends` 拉好友列表，队友表里区分
   "好友/路人"，这正好是上次那锅争论的核心。
3. **配对检验**：同一批我在场、队友不同的对局互相比，而不是拿每行胜率去和全局比。
4. **实时**：对局中用 `GET /lol-gameflow/v1/session` 抓当前对局，赛后自动入库。
5. **打包体积**：PySide6 全量约 150MB，可以按需裁掉 QtWebEngine 等用不到的模块。
