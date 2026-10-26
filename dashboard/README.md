# Topic Log dashboard · Topic Log 看板

**Status 状态:** v2 · scoring w2 (default 默认) · claude.ai dashboard refreshed 3×/day (07, 15, 23 ET) 每天刷新 3 次 · desktop app 桌面 app `Topic Log.app` v0.6 · every pull archived 每次拉取永久存档 · agenda 3–5 added 已加入议程 3–5 (venue appendix 场所附录, Adanos sectors 板块 + news 新闻, briefing 解读)

Agenda item 1 (10/16): one place to see, every few hours, which market topics people are talking about and trading on, rank them for the day's MYCAST episode, and tune the ranking by hand. The pick of record is the first pull at or after 15:00 ET.

议程第 1 项（10/16）：一个地方，每隔几小时看到大家在讨论、在交易哪些市场话题，为当天的 MYCAST 节目排序，并且可以手动调整排序。每天的正式选题是美东 15:00（含）之后的第一次拉取。

Deeper write-up with the backtests: the "Topic Log Dashboard Briefing" doc and the "Topic Log Backtest v3" page.
更详细的说明和回测：见「Topic Log Dashboard Briefing」文档和「Topic Log Backtest v3」页面。

---

## 1. The overall logic · 整体逻辑

```
every pull 每次拉取 (cloud 云端: 07:00, 15:00, 23:00 ET 每天 3 次 · desktop 桌面: your interval, default 8 h 你设的间隔，默认 8 小时)
  1. collect   抓取     Kalshi · Polymarket · Adanos (Reddit, X, News) · prices 价格 (Yahoo; Binance → Coinbase → Kraken)
                        + supporting 辅助: Nasdaq stock list 股票列表, Nasdaq earnings 财报, Yahoo movers 异动, Kalshi perps 永续合约
  2. topics    生成话题  every item gets a topic automatically 每条东西自动归到一个话题 (registry.py)
  3. inputs    各源填数  each source fills only its own columns 每个源只写自己的列, nothing counted twice 不重复计算
  4. combine   合成指标  source columns → 9 components 9 个指标
  5. gates     过门槛    G2 · G3 remove topics that can't carry an episode 筛掉撑不起一期节目的话题
  6. score     打分      within-pull percentile per component → weighted mean 每个指标取当次百分位 → 加权平均
  7. rank      排名      sort, record the 15:00 ET pick 排序、记录每日选题
  8. briefing  解读      venue appendix, Kalshi perps, Adanos sectors and news; cloud: Claude writes the briefing 场所附录、永续合约、Adanos 板块和新闻；云端由 Claude 写解读
  9. save      保存      18 datasets + archive 18 个数据集 + 存档
```

The page redoes steps 4–7 in the browser every time you move a control, so tuning is instant. Nothing you change is written back to the data; the stored ranks (`w0 #`, daily picks) stay as the pipeline computed them.

页面在你每次调整时，会在浏览器里重算第 4–7 步，所以调参是即时的。你的调整不会写回数据；存储的名次（`w0 #`、每日选题）保持后台算出的结果。

### Topics and events · 话题与事件

A **topic** is what an episode would be about (a stock, a coin, an index, the Fed, CPI, a private company…). An **event** is one market or item under it (a Kalshi event, a Polymarket event, a Yahoo mover). Assignment order, first hit wins:

**话题**是一期节目会讲的主题（股票、币、指数、美联储、通胀、私人公司……）。**事件**是话题下面具体的一个市场或条目。归类顺序，先命中的生效：

1. Kalshi rules in `symbols.py` (KPI / point-of-sale / app-download series → the stock; Economics series → FED, CPI, JOBS, GDP, HOUSING…)
   Kalshi 规则（KPI、销售点、app 下载系列 → 对应股票；经济类系列 → 宏观话题）
2. A ticker in the text (`$NVDA`, `(KO)`) or a known ticker; ETFs → what they track (SPY → SPX, GLD → GOLD)
   文字里的股票代码；ETF 归到它跟踪的东西
3. A known name or alias (macro terms, indices, commodities, coins, private companies, the 1,500 largest US companies); longest match wins
   已知名称或别名；最长匹配优先
4. Nothing matched → a **new topic** of its own, marked `new`
   都没对上 → 自己成为**新话题**，标 `new`

No manual mapping. New topics are listed in **Topics & events** (filter "New only"). 不需要人工对应。

### The nine components · 9 个指标

| Component 指标 | Source 来源 | Raw value 原始值 |
|---|---|---|
| Attention 关注度 | Adanos, platforms switched on 打开的平台 | **w1, w2:** yesterday's mentions vs the topic's own mean over the 19 days before (log ratio, platforms summed) 昨天提及数比自己前 19 天平均（对数比，平台加总）. **w0:** 1-day buzz change 单日热度变化 |
| Attention on X · X 关注度 | Adanos X | X mentions vs X's own 20-day normal X 提及数比自己 20 天平均 (w2) |
| Activity 活跃度 | Adanos | **w1:** last 3 days vs the 3 before 三日比前三日. **w0:** 1-day change 单日变化 |
| Money flow 资金流入 | Kalshi + Polymarket, weighted by each venue's 24h volume 按成交量加权 | Kalshi: 24h volume vs 24h earlier 比 24h 前; Polymarket: vs its 1-week average 比一周均值 |
| Money stock 持仓量 | Kalshi + Polymarket, weighted by OI 按持仓加权 | **w2:** OI vs its own mean over earlier pulls (≥3 days, ≤10) 比自己平常. **w0, w1:** vs 24h earlier 比 24h 前 |
| Market move 概率变动 | Kalshi + Polymarket | volume-weighted \|probability change\| over 24h, two-sided traded markets only 24h 概率变动幅度，按成交加权 |
| Sentiment 情绪 | Adanos | \|1-day sentiment change\| 情绪单日变化幅度 |
| Momentum 动量 | prices 价格 | \|24h price change\| ÷ the month's daily volatility 涨跌幅 ÷ 日波动率 |
| Volume 成交量 | prices 价格 | traded so far today vs the same hours of the previous 20 sessions (log ratio); coins: 24h volume on the price venue vs its 20-day mean 今天到目前的成交量比前 20 天同时段 (w2) |

Adanos uses complete UTC days only (yesterday and earlier). Crypto has Reddit only.
Adanos 只用完整的 UTC 日（昨天及以前）。加密货币只有 Reddit。

### Gates · 门槛

| Gate 门槛 | Rule 规则 | Default 默认 |
|---|---|---|
| G2 | prediction-market volume (Kalshi or Polymarket) in the last 24h · 24h 内有预测市场成交 | on: "prediction-market volume" |
| G3 | on the 3 Kalshi strikes nearest 50%: zero-trade share ≤ 80%, average spread ≤ $0.30 · 最接近 50% 的 3 个档位：零成交比例 ≤ 80%，平均价差 ≤ 0.30 美元 | on |

G4 (cooldown after an episode) waits for an episode log. G4（做过节目后的冷却期）要等有节目记录。

### Score · 得分

`score = quality × Σ wᵢ · pctrank(xᵢ) / Σ wᵢ`

- `pctrank` = the topic's percentile among topics that passed the gates this pull; 0.8 ≈ "ahead of 80% of today's pool". 当次过了门槛的话题里的百分位；0.8 ≈ 超过今天 80% 的话题。
- Missing input: w1 and w2 count it as 0.5 (the median); w0 leaves it out and rescales the weights. 缺数据：w1、w2 按中位数 0.5 算；w0 去掉并重分权重。
- **Quality multiplier** (off in w1, w2) 质量系数（默认关）: `spread factor × zero-trade factor × source factor`. Spread factor = 1 up to the free spread, then falls by `(spread − free) / slope`, never below the floor; zero-trade factor = 1 − penalty × zero-trade share; source factor = 1 with both market and social data, else the single-source factor.
- **Tiers** 分层: T1 = a catalyst (earnings, KPI market, CPI/FOMC) within N trading days and strong move or flow 有催化剂且市场活跃; T2 = strong flow and attention 资金和关注都强; T3 = strong attention 关注强; T4 = the rest 其余.

### w0, w1, w2

| | w0 (playbook 原版) | w1 (Oct 23) | **w2 (default 默认, Oct 24)** |
|---|---|---|---|
| Attention 关注度 | .25, 1-day buzz 单日热度 | .30, vs normal 比平常 | **.35**, vs normal 比平常 |
| Attention on X · X 关注度 | – | – | **.35** |
| Activity 活跃度 | .10, 1-day | .10, 3-day | 0 |
| Money flow 资金流入 | .20 | .15 | 0 |
| Money stock 持仓量 | .10, Δ24h | .10, Δ24h | **.05**, vs normal 比平常 |
| Market move 概率变动 | .20 | .10 | 0 |
| Sentiment 情绪 | .15 | 0 | 0 |
| Momentum 动量 | 0 | .25 | **.125** |
| Volume 成交量 | – | – | **.125** |
| Missing input 缺数据 | dropped 去掉 | median 中位数 | median 中位数 |
| Quality · Tiers 质量 · 分层 | on · rank 开 · 按层排 | off · labels 关 · 标签 | off · labels 关 · 标签 |

Why w2 (study v3, `backtest/v3/`): target = 70% next-day attention + 30% next-session abnormal price move. On 15 holdout days w2 reached rank IC 0.37 vs 0.28 (w1), 0.02 (w0), 0.11 (momentum only); its top 5 landed at the 72nd percentile.

为什么是 w2（v3 回测，`backtest/v3/`）：目标 = 70% 第二天关注度 + 30% 第二天价格异常波动。在 15 天验证期里 w2 的 IC 为 0.37，w1 0.28、w0 0.02、只看动量 0.11；每天前 5 名平均排在第 72 百分位。

Stored fields 存储字段: w0 = `rank`, `demand_score`; default ranking 默认排名 = `pick_rank`, `pick_score`, `pick_tier` (`pick_version` in the run log). Daily picks 每日选题: w0 until Oct 22, w1 on Oct 23, w2 from Oct 24.

---

## 2. Every control · 每个按钮和板块

### Top of the page · 页面顶部

- **Take line 摘要行**: latest pull time, your pick with the current settings, the stored w0 pick, the momentum pick. 最近一次拉取时间、你当前设置下的第一名、w0 的第一名、动量的第一名。
- **Tabs 标签页**: Workbench · Briefing · Raw data · Daily picks · Daily steps · Market data · Topics & events.

### Workbench · 1 · IN — data sources (left) · 左栏：数据源

- **Kalshi / Polymarket switch 开关**: take that venue out of money flow, money stock and market move. With both off, G2 "prediction-market volume" removes every topic. 把该平台移出资金、持仓、概率三个指标；两个都关时 G2 会把所有话题筛掉。
- **Adanos · Reddit / X / News chips**: which platforms feed attention, attention on X, activity and sentiment. 选哪些平台参与社交指标。
- **Prices switch 价格开关**: momentum and volume on or off. 动量和成交量开关。
- **View**: opens that source's raw table in Raw data. 跳到原始数据表。
- **Status dot 状态圆点**: green ok, amber partial / no key / empty, red error (latest pull). 绿正常、黄部分、红出错。
- **Supporting sources 辅助源**: Yahoo movers (adds topics 加话题), Nasdaq earnings (T1 catalysts 催化剂), Nasdaq US stocks (tickers and names for matching 用于匹配), Binance · Coinbase · Kraken (coin list and prices 币列表和价格). Not scored directly. 不直接打分。
- **eToro / Metrixx AI upload**: placeholders 占位 (eToro needs a key 需要 key; Metrixx upload = agenda item 2 议程第 2 项).
- **Universe · Topic sources 话题来源**: keep only topics from the chosen sources (Kalshi, Polymarket, Adanos trending, US movers); a topic with several sources stays while any is on. 只保留来自所选来源的话题。
- **Universe · Asset classes 资产类别**: equity, macro, crypto, theme, commodity, index, private, fx, rates; a chip switched off removes that class. 关掉某类即移除。
- **Inputs with data 指标覆盖率**: share of topics with a value for each component this pull. 本次每个指标有数的话题占比。

### Workbench · 2 · SCORE — algorithm (middle) · 中栏：算法

- **Reset to w2** (default 默认) · **Load w1** · **Load w0**: presets for comparison. 一键切换版本。
- **Export as YAML 导出**: current settings as a `weights_wN.yaml` draft for `config/`. 当前设置导出为配置草稿。
- **Weights 权重**: one slider per component; the bar shows its share of the total. 每个指标一个滑块，下方条形显示占比。
- **Attention measure 关注度算法**: vs normal (w1, w2) / 1-day buzz (w0). **Activity measure 活跃度算法**: 3-day / 1-day. **Money stock measure 持仓量算法**: vs normal (w2) / 24h change (w0, w1). **Missing input 缺数据**: median (w1, w2) / drop (w0).
- **Hard gates 门槛**: G2 mode (prediction-market volume / any market or social activity / off 关) · G3 max zero-trade share 零成交上限 · G3 max spread 价差上限.
- **Quality multiplier 质量系数**: on/off, free spread 免费价差, spread slope 斜率, spread floor 下限, zero-trade penalty 零成交惩罚, single-source factor 单一来源系数.
- **Priority tiers 分层**: rank by tier / labels only / off; T1 catalyst window (trading days) and the percentile thresholds for T1–T3. 按层排 / 只做标签 / 关；T1 催化剂窗口和各层门槛。

### Workbench · 3 · OUT — output (right) · 右栏：输出

- **Your pick / Pool / Top 10 shared with w0**: rank 1 with your settings; topics passed vs gated; overlap with the stored w0 top 10. 你的第一名；过门槛和被筛的数量；与 w0 前 10 的重合。
- **Search 搜索** and **Show gated 显示被筛话题** (with the gate that removed them 及原因).
- **Ranked table 排名表**: `#` your rank (▲▼ vs w0 相对 w0 的升降), `w0 #`, Topic (`new` = created this pull 本次新建), Name, Class, From (K Kalshi · P Polymarket · A Adanos · M movers), Tier, Score, nine component percentiles (attn, attn X, activity, flow, OI, move, sent, mom, vol), Quality, Gate. Click a header to sort, a row to open it. 点表头排序，点行展开。
- **Topic breakdown 话题详情**: score arithmetic 得分计算, catalyst 催化剂, each component's percentile and points 各指标百分位和贡献分, raw inputs from every source 每个源的原始数字, rank over the last 10 days 近 10 天名次, most traded events 成交最多的事件.
- **Your score vs momentum 得分 vs 动量**: every scored topic; right = higher score, up = larger abnormal move. 右 = 得分高，上 = 异常波动大。

### Briefing · 解读 (agenda 4, 5 · 议程第 4、5 项)

- **Today's read 今日解读**: three short notes, sectors · news on the top topics · why the top picks rank where they do. On the cloud, Claude writes them on every pull from that pull's data (marked "read by Claude"); in the desktop app they are an automatic summary built from the same numbers. Facts only, no investment advice. 三段短评：板块、头部话题的新闻、前几名为什么排在那里。云端每次拉取由 Claude 根据当次数据撰写；桌面 app 里是按同样数字自动生成的摘要。只讲事实，不给投资建议。
- **Sectors on Adanos 板块变化**: Adanos' trending sectors for the last complete day, one table per platform (chips News / X / Reddit). Columns: `#` rank (and the day before), Sector, Buzz (Adanos 0–100), Δ day, Δ 7-day, a 7-day buzz line, Mentions and Δ%, Sentiment (−1 to 1), Bull % / Bear %, Top tickers driving it. Click a header to sort. 最近一个完整日的热门板块，每个平台一张表（点 News / X / Reddit 切换）。列：名次（及前一天名次）、板块、热度（0–100）、日变化、7 日变化、7 日热度线、提及数及变化%、情绪、看多/看空比例、带动该板块的股票。点表头排序。
- **News on today's top topics 头部话题新闻**: Adanos news of the last 2 days for the 15 best-ranked stock topics (by the default ranking), up to 4 per topic: a coloured dot for sentiment, the headline, source and time. Only articles that name the ticker or company; fund-filing boilerplate ("XYZ fund bought shares of…") is left out. Adanos gives text snippets, not links, so there is no click-through. 按默认排名前 15 的股票话题，过去 2 天的 Adanos 新闻，每个话题最多 4 条：情绪色点、标题、来源和时间。只保留提到该代码或公司名的文章，去掉基金持仓公告类的套话。Adanos 只给文字摘要、不给链接，所以不能点开原文。
- The topic breakdown in the Workbench also shows the topic's Kalshi perp and its news lines. 工作台的话题详情里也会显示该话题的永续合约和新闻。

### Other tabs · 其他标签页

- **Daily picks 每日选题**: rank-1 pick of each day's 15:00 ET pull (chart) and top 5 per day (table). 每天的第一名（图）和前 5（表）。
- **Daily steps 拉取日志**: one row per pull: when, scored / gated counts, each source's status. 每次拉取一行。
- **Raw data 原始数据**: every source as a searchable, sortable table. 每个源一张可搜索可排序的表。
- **Market data 行情**: price, 24h and 5-day change, abnormal move per priced topic (the Metrixx upload will join here). 价格、涨跌、异常波动。
- **Topics & events 话题与事件**: tiles per asset class; every topic with its sources, how it was matched (rule, ticker, name, new) and event count; click a topic to filter events; every Kalshi series and its topic. 每个话题的来源和匹配方式，点话题看事件。
- **Venue appendix 场所附录** (in Topics & events, agenda 3 · 议程第 3 项): every topic and everywhere it trades or is talked about: Kalshi events, Kalshi perp (ticker, OI in $, latest 8-hour funding rate), Polymarket events, Adanos platforms with data, the price symbol, and the crypto exchanges (Binance · Coinbase · Kraken, crypto topics only). **Venues** = how many of these list it. Search, asset-class chips and **Has a perp** filter it. 每个话题在哪里交易、在哪里被讨论：Kalshi 事件数、Kalshi 永续合约（代码、持仓美元、最近 8 小时资金费率）、Polymarket 事件数、Adanos 有数据的平台、价格代码，以及加密交易所（Binance、Coinbase、Kraken，仅加密话题）。**Venues** = 上述场所中有几个列了它。可搜索、按资产类别筛选、只看有永续合约的。
- **Kalshi perps 永续合约**: Kalshi's perpetual futures (no expiry; long/short, kept near the spot price by a funding rate paid every 8 hours). Listed under supporting sources and in Raw data; shown in the appendix and the topic breakdown, **not scored** yet. Kalshi 的永续合约（不到期，可做多做空，每 8 小时用资金费率把价格拉向现货）。在辅助源和原始数据里可看，显示在附录和话题详情中，暂**不参与打分**。

### Desktop app · 桌面 app (`Topic Log.app`)

- **Pull every 拉取间隔** (15 min, 30 min, 1 h, 3 h, 8 h, 12 h, 24 h; default 8 h = 3 pulls a day 默认 8 小时，即每天 3 次): the next pull moves to the new interval; it does not pull at once. 改了只影响下一次时间，不会马上拉。 With 24 h, pull after 15:00 ET so the day gets a pick, and after 17:00 ET for the daily archive parts. 选 24 小时的话，最好在美东 15:00 之后拉，当天才有选题；17:00 之后拉才会存每日全量。
- **Pull now 立即拉取**: fetch every source now (a few minutes; the dot turns amber). 几分钟，进行中圆点变黄。
- **Refresh view 刷新显示**: reload the page from data already on the Mac. 用 Mac 上已有的数据重载页面。
- **Adanos key… 填 key**: stored in `~/Library/Application Support/TopicLog/settings.json` (mode 600). **Quit 退出**.
- Data, history and archive live in `~/Library/Application Support/TopicLog/data/`, separate from the cloud dashboard; page settings are kept per Mac. 数据、历史和存档在这个文件夹，与云端独立；页面设置保存在本机。
- First start uses the pull shipped in the app; after an update the data on the Mac is kept unless the shipped pull is newer. 第一次启动用安装包里附带的数据；更新时如果 Mac 上的数据更新，就保留本地数据和历史。
- Build 打包: `SEED=<dir of a pull> ./desktop/build.sh [ADANOS_API_KEY]` → `desktop/dist/Topic Log.app`. Build without a key for anyone else. 给别人用时不要带 key。

### Windows app · Windows 版 (`TopicLog.exe`)

- One file, no Python needed: double-click `TopicLog.exe`. Same page, buttons and data as the Mac app. 单个文件，不用装 Python，双击即可；页面、按钮、数据和 Mac 版一样。
- The Adanos key sits in `settings.default.json` **in the same folder as the .exe**; without it, use the **Adanos key…** button. 把 key 放在和 exe 同一个文件夹的 `settings.default.json` 里；没有这个文件时用 **Adanos key…** 按钮填。
- Data, history and archive: `%APPDATA%\TopicLog\` (paste it into the Explorer address bar). The first start has no data until the first pull finishes (a few minutes). 数据在 `%APPDATA%\TopicLog\`；第一次打开要等第一次拉取完成（几分钟）才有数据。
- The window is a native window (Edge WebView2, built into Windows 10/11); if that fails it opens as an Edge app window. 窗口用 Windows 自带的 Edge 内核；不行时用 Edge 应用窗口打开。
- The .exe is not signed: Windows may show "Windows protected your PC" → **More info → Run anyway**. 没有签名，Windows 可能提示"已保护你的电脑"，点"更多信息 → 仍要运行"。
- To stop it, press **Quit** in the app bar (closing the window also stops it). 用 **Quit** 退出（关窗口也会退出）。
- Build 打包: GitHub Actions builds it on every push that touches the app (`.github/workflows/windows-app.yml` → `desktop/windows/build_win.py`), runs a real pull as a self-test, and keeps `TopicLog.exe` as a 7-day artifact. The repo is public, so the .exe never carries the key. 每次推送由 GitHub Actions 自动打包并自测一次真实拉取；仓库是公开的，所以 exe 里永远不放 key。

---

## 3. For developers · 开发说明

```bash
python -m dashboard.pipeline --state STATE_DIR --out OUT_DIR --adanos-key "$ADANOS_API_KEY"   # or ADANOS_KEY env
```

`STATE_DIR` holds the previous `score_history.json`, `daily_log.json`, `runs.json`, `adanos_daily.json` (any may be missing). The cloud scheduled task downloads them from the dashboard, runs this, has Claude rewrite `briefing.json` from `sectors.json`, `news.json` and the top 10 topics, uploads the 18 outputs, repoints the datasets, then runs `dashboard/archive_push.sh out`.

`STATE_DIR` 放上一次的 4 个状态文件（可缺）。云端定时任务从看板下载它们、运行、让 Claude 根据板块、新闻和前 10 名重写 `briefing.json`、上传 18 个输出、更新数据集，再推送存档。

| File 文件 | What 内容 |
|---|---|
| `pipeline.py` | steps 1–7, w0 and the default (w2) ranking · 主流程 |
| `registry.py` | automatic topics · 自动归类 |
| `symbols.py` | Kalshi rules, aliases, topic metadata · Kalshi 规则、别名、话题信息 |
| `sources.py` | free sources · 免费数据源 |
| `briefing.py` | venue appendix, Kalshi perps, Adanos sectors and news, automatic briefing · 场所附录、永续合约、板块、新闻、自动解读 |
| `archive.py`, `archive_push.sh`, `adanos_universe.json` | permanent archive · 永久存档 |
| `catalysts.yaml` | CPI / FOMC dates · 宏观日历 |
| `page/index.html` | the dashboard page (cloud and app) · 看板页面 |
| `backfill/` | history pulls for backtests · 回测用的历史数据脚本 |

Outputs 输出 (one JSON per dataset 每个数据集一个 JSON): `topic_log` (one row per topic 每个话题一行), `events`, `score_history` (10 days), `daily_log` (45 days), `runs`, `adanos_daily`, `symbol_appendix`, `market_data`, `kalshi_perps`, `venue_appendix`, `sectors`, `news`, `briefing`, plus raw `us_stocks`, `earnings_calendar`, `us_movers`, `polymarket`, `crypto_spot`.

### Archive · 存档

Every pull writes what it saw to `archive/` (gzipped JSON): Kalshi markets, Kalshi perps (price, OI, funding), Polymarket, US movers, topic log and events on every pull; US stocks, crypto spot and earnings once a day after 17:00 ET; one complete day of Adanos (~4,800 stocks, ~180 coins, Reddit / X / News) once a day. The cloud appends it to the repo's `archive` branch (~5 MB/day); the app keeps it locally.

每次拉取把看到的数据压缩存进 `archive/`：每次存 Kalshi 市场、永续合约、Polymarket、异动、话题表和事件；每天 17:00 后存美股全表、加密现货、财报；每天存一次 Adanos 全量（约 4800 只股票、180 个币，三个平台）。云端推到仓库的 `archive` 分支（每天约 5 MB），app 存在本地。

---

## 4. Known limits · 已知局限

- Money flow and OI change need a pull from about 24h earlier; OI vs normal needs 3 days of history. After a fresh start they are empty and count as the median. 资金流入和持仓变化需要约 24h 前的数据，持仓比平常需要 3 天历史；刚启动时为空，按中位数算。
- Social data in the backtest covers 43 days only (Adanos key limit); re-validate w2 on archived days in mid-November. 回测里的社交数据只有 43 天；11 月中用存档数据复验 w2。
- The target is a proxy (next-day attention and price move); real episode views and listens are the better target once they exist. 目标是代理指标；有节目播放数据后应换成真实反馈。
- Polymarket volume history is not available from the API; Kalshi perps are shown and archived but not scored yet (only ~40 contracts, mostly crypto and indices). Polymarket 没有成交量历史；永续合约已显示和存档但未打分（只有约 40 个，大多是加密和指数）。
- News comes from Adanos snippets: no links, and some headlines are cut. Sector reads use 2 extra Adanos calls per platform per pull and news 15. 新闻来自 Adanos 摘要：没有链接，部分标题被截断。板块每次每平台多 2 次调用，新闻 15 次。
- Kraken has no perps API wired in; it appears through the crypto exchange flags only. Kraken 只通过加密交易所标记出现，没有接入它的永续合约。
- G4 cooldown is inactive until an episode log exists. G4 冷却期要等有节目记录。

---

Back to the [project README](../README.md). 返回项目 README。
