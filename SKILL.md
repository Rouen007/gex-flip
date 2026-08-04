---
name: gex-flip
description: 从期权 GEX heatmap 的 per-strike 数据反算 Gamma Flip（个股 / ETF / 指数通用），含可信度评分、瞬移风险、机制解读。算法已在 SPX 60天4677帧 + 10只个股23组到期上 100% 精确复现官方 gammaFlip。触发词："flip", "gamma flip", "算一下 XXX 的 flip", "flip 在哪", "heatmap 推 flip", "个股 flip", "翻转点", "zero gamma", "正负 gamma 分界"
version: 1.0.0
tags: [gex, gamma, flip, heatmap, options, nightwatch, yehangshe, dealer, single-stock]
triggers:
  - flip
  - gamma flip
  - gex-flip
  - 算 flip
  - 推 flip
  - 翻转点
---

# gex-flip · 从 heatmap 推算 Gamma Flip

## 什么时候用

用户问「XXX 的 flip 在哪」「盘前 heatmap 怎么推 flip」「flip 是什么机制」
「这个 flip 可信吗」——不管是个股、ETF 还是指数。

## 直接跑

```bash
python3 ~/.claude/skills/gex-flip/flip.py TSLA              # flip + 可信度评分
python3 ~/.claude/skills/gex-flip/flip.py TSLA NVDA AAPL    # 批量
python3 ~/.claude/skills/gex-flip/flip.py TSLA --chart      # 附终端版 heatmap 列，对着图核对
python3 ~/.claude/skills/gex-flip/flip.py --manual 315:-83.8 317.5:300.6 --spot 323.45
                                                            # 只有截图没接口时，手敲两档值
```

依赖：`opencli` 浏览器会话（默认 `svb6mefm`，可用环境变量 `YHS_SESSION` 改）停在
已登录的 yehangshe.com。脚本会自己把页面拉回站内，不用手动开。

---

## 算法（三步，指数个股通用）

给定 heatmap 一列（= 一个到期日 expiryGroup）的 `(行权价, netGex)`：

1. 按行权价升序
2. 找**相邻两档之间 netGex 符号翻转**的位置，线性插值：
   `x = K低 + (K高−K低) × |netGex低| / (|netGex低| + |netGex高|)`
3. 通常有多个零点 → **取离当前现价最近的那一个** = flip

**验证**：SPX 60 天 / 4677 帧 + 10 只标的 23 组到期，**全部零偏差精确复现官方 `gammaFlip`**。

### ⛔ 不是累加和（cumsum）穿零

| 口径 | SPX 中位误差 | 精确复现率 |
|---|---|---|
| **单格符号翻转 + 取最近现价** | **0.00 点** | **100%** |
| 累加和穿零 | 19.16 点 | 0% |
| 从高到低累加 | 150.80 点 | 0% |
| 上下分割 `Σ下 − Σ上` | 37.23 点 | 0% |

---

## 机制（回答"flip 是啥"时用这套）

**flip = put（看跌期权）持仓主导 翻成 call（看涨期权）持仓主导 的那个价位。**

1. 符号约定（实测全链零违例）：`callGex ≥ 0`、`putGex ≤ 0`，
   `netGex(K) = callGex(K) − |putGex(K)|` → 这一档哪边持仓占优
2. 背后假设：做市商 **long call gamma / short put gamma**。
   ⚠️ 行业惯例假设，不是实测持仓——Dealer GEX 才是想真分离做市商那一边的
3. 为什么单格符号能代表制度分界：gamma 在行权价处最大、远离迅速衰减 → 现价附近
   那几档的净符号 ≈「现价在这里时做市商净 gamma 的符号」。
   **这是局部近似，不是全局积分**——所以取"最近现价"而不是累加，也所以它会瞬移
4. 制度含义：
   - flip **上方** = 做市商净 long gamma → 对冲是高抛低吸 → **抑制波动、价格被钉住**
   - flip **下方** = 做市商净 short gamma → 对冲是追涨杀跌 → **放大波动、容易加速**

⚠️ 严格说这不是真正的「零 gamma 点」：每档 gamma 用**当前现价**算的，不是"假设现价移到
那里"重算 BS gamma。flip 是结构分界的**近似标记**，不是精确物理阈值。

---

## 个股三个独有的坑（指数上没有）

### 1 · 分辨率粗 6-20 倍

| 标的 | 档距占现价 |
|---|---|
| SPX | 0.067% |
| SPY / QQQ | 0.13-0.14% |
| META / MSFT | 0.43-0.50% |
| AAPL / GOOGL / AMZN / TSLA | 0.66-0.90% |
| **NVDA** | **1.19%** |

→ **个股上给 flip 报小数点没有意义**。

### 2 · 瞬移幅度灾难级

定义是"最近现价"，现价一动 flip 就切到下一个翻转点。次近翻转点距离：

| 标的 | 跳幅 |
|---|---|
| SPY / QQQ / MSFT | 0.15% – 0.37% |
| GOOGL / AMZN / META | 0.25% – 1.2% |
| TSLA 1dte / IWM | 2.2% – 2.8% |
| AAPL | 7% – 12% |
| **NVDA** | **14% – 16%** |
| **TSLA weekly** | **31.5%** |

### 3 · 常常是「薄」的

个股期权链稀疏，翻转可能只由一档小单造成。
**厚度 = 夹住 flip 的两档中较大的 |netGex| ÷ 全链最大节点**：

- ≥20% = 厚，可信 　·　5-20% = 中等 　·　**<5% = 噪音，别当位用**

更狠的：只保留量级 ≥ 全链最大节点 5% 的档重算。2026-08-04 实测 **NVDA 的 1dte 和
weekly 过滤后翻转点直接消失** → 那个 flip 是假位，结构其实是单向的。
`flip.py` 会自动跑这个检验并报警。

---

## ⛔ 别拿它做方向（56 天回测，无未来函数）

| flip 取值时点 | 上方组收涨 | 下方组收涨 | 区分度 |
|---|---|---|---|
| ① D-1 收盘帧（**盘前真正可用**） | 60% | 61% | **−1pp** |
| ② D 当天 9:30 首帧 | 71% | 48% | +23pp（仅 1.8σ，不显著） |
| ③ D 收盘帧 vs 收盘价（⚠️未来函数） | 77% | 36% | +41pp |
| ④ D 收盘帧 vs 开盘价（⚠️未来函数） | 44% | 86% | **−42pp（符号翻转=典型未来函数特征）** |

基准收涨 60%，n=53。**盘前算的 flip 对方向零信息量**——D-1 收盘帧到次日开盘中位漂移
**21.45 点**（<5 点的只占 12%），现价一动"最近翻转点"就换人。

② 的 +23pp 只在**全天收盘**上出现，切到早盘 9:30-12:00 就消失（53% vs 基准 52%）。

入场位同样无效：触及 flip 后 30 分钟位移与随机价位无差别；盘前最大正节点当目标位，
早盘触达率 **69% vs 随机 69%（+0pp）**；flip 当止损 + 2R 目标中位 **−1.00R**。

### ⭐ 正确的用法：它管"波动性质"不管"方向"

- flip **不告诉你涨还是跌**，告诉你**今天这票是被钉住还是会跑**
- 佐证：`SPX_rules.md` S3「负 GEX 日振幅 85.4 vs 正 62.5（**+37%**）」——这条是活的
- 新发现（SPX，p=0.001）：盘前 heatmap **开盘价 ±25 点内的翻转点个数 → 早盘趋势度**
  （净位移÷振幅）：0 个 = 0.272、1-2 个 = 0.377、≥3 个 = **0.761**。
  振幅几乎不变（52/51/53）→ 不是波动率效应。
  **反直觉：结构越碎越走单边，越干净越磨回原地。**
  ⚠️ n=14/23 偏小，**只在 SPX 上测过，个股未测**（个股翻转点少，±25 点绝对阈值也要改百分比）

---

## 数据接口

```
# 个股 / ETF 实时（expiryGroup 就是 heatmap 的到期日列）
/api/gex/intraday-history?ticker=<T>&expiryGroup=1dte&bucket=5m&session=today&profile=standardGexOverlay
  → data.latestPayload.expiryGroups[<组>].strikes[]   {strike, netGex, callGex, putGex, callOi, putOi}
  → data.latestPayload.expiryGroups[<组>].summary.gammaFlip   官方值，用来对答案
  expiryGroup: 0dte / 1dte / weekly（monthly、all 返回 400）
  ⚠️ 一次请求把该 ticker 所有可用到期组一起返回，不用逐个拉

# SPX 历史回放（90 天滚动）
/api/replay-lab/day-overlays?ticker=SPX&date=YYYY-MM-DD&dealerGexSignConvention=dealer-signed-v1
  → data.standardGexFrames[].strikes[]
```

⚠️ **口径**：以上都是 **Standard GEX**（全市场）。Dealer GEX Heatmap 是**做市商一方**，
同一行权价量级差三个数量级，两者的 flip 不是同一条线，**别互相验证**。

---

## 文件

| 路径 | 用途 |
|---|---|
| `flip.py` | 主工具：算 flip + 可信度评分 + 终端版 heatmap |
| `test_flip.py` | 离线自检（真实盘面固定用例，不联网不要数据集） |
| `docs/methodology.md` | 完整方法论与全部回测数据 |
| `research/analyze_flip_from_strikes.py` | 复现验证（60 天 / 4677 帧） |
| `research/analyze_flip_lookahead.py` | 三时点未来函数对照 |
| `research/analyze_crossing_density.py` | 翻转点密度 → 趋势度（唯一活着的发现） |
| `research/analyze_premarket_flip_entry.py` | 盘前入场/目标位回测（含零模型） |
| `research/analyze_flip_entry_rules.py` | 建仓规则回测（方向/距离档/止损目标，含 Wilson 区间） |
| `research/analyze_flip_stability.py` | 瞬移量化 |
| `research/flip_mechanism_check.py` | put/call 主导验证 |
| `research/scan_universe.py` | 跨标的批量验证 + 分辨率/瞬移风险表 |
| `research/harvest_strikes.sh` | 采 SPX 历史 per-strike 数据 |

`research/*` 需要本地数据集，路径用环境变量 `GEXFLIP_DATA` 指定
（默认 `~/trading-reports/nightwatch_replay_dataset`）。

关联：[[nightwatch-daily]]、[[project_nightwatch_heatmap]]、[[feedback_gex_index_vs_single_stock]]
