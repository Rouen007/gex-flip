#!/usr/bin/env python3
"""基于 heatmap 自算 flip 的建仓规则回测（早盘 9:30-12:00，用户框架）
   含二项显著性检验 + 无条件基准对照。"""
import json, glob, os, math, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))
MEND = 150          # 12:00 ET


def crossings(strikes, net):
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0: continue
        out.append(strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0))
    return out


def prop_ci(k, n):
    """Wilson 95% 区间"""
    if n == 0: return (0, 0)
    p = k/n; z = 1.96
    d = 1+z*z/n
    c = (p+z*z/(2*n))/d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/d
    return (max(0, c-h)*100, min(1, c+h)*100)


days, strikes = {}, {}
for p in sorted(glob.glob(f"{DIR}/day_*.json")):
    d = json.load(open(p))
    if d.get("bars"): days[d["date"]] = d
for p in sorted(glob.glob(f"{DIR}/strikes/st_*.json")):
    d = json.load(open(p))
    if d.get("frames"): strikes[d["date"]] = d
dates = sorted(set(days) & set(strikes))

S = []
for i in range(1, len(dates)):
    D, P = dates[i], dates[i-1]
    bars = days[D]["bars"]
    if len(bars) < MEND: continue
    fr = strikes[D]["frames"]
    f930 = fr[0].get("flip")
    prev = strikes[P]["frames"][-1]
    cs_pre = crossings([r[0] for r in prev["s"]], [r[1]*1e3 for r in prev["s"]])
    if f930 is None or not cs_pre: continue
    o = bars[0]["open"]
    m = bars[:MEND]
    S.append(dict(date=D, o=o, f930=f930, bars=bars, m=m,
                  mh=max(b["high"] for b in m), ml=min(b["low"] for b in m),
                  mc=m[-1]["close"], dc=bars[-1]["close"],
                  pre_cross=cs_pre, prev_close=prev["spot"],
                  # 盘前 heatmap 的正节点（当目标位候选）
                  pos=sorted([(r[0], r[1]*1e3) for r in prev["s"] if r[1] > 0],
                             key=lambda r: -r[1])[:5]))

print(f"样本 {len(S)} 天 ({S[0]['date']} ~ {S[-1]['date']})")
base_up = sum(1 for s in S if s["mc"] > s["o"])
print(f"早盘基准：收涨 {base_up}/{len(S)} = {base_up/len(S)*100:.0f}%  "
      f"中位位移 {st.median(s['mc']-s['o'] for s in S):+.1f} 点\n")

# ---------- 规则 1：9:30 flip 定方向，开盘价入场，12:00 平 ----------
print("="*78)
print("规则1 · 9:30 首帧 flip 定方向 → 开盘即入场 → 12:00 平仓（早盘框架）")
print("="*78)
print(f"{'分组':<26}{'n':>4}{'胜率':>8}{'95%区间':>16}{'中位R点':>10}{'均值R点':>10}")
for nm, sel, sign in [("open > flip → 做多", lambda s: s["o"] > s["f930"], +1),
                      ("open < flip → 做空", lambda s: s["o"] < s["f930"], -1)]:
    g = [s for s in S if sel(s)]
    if not g: continue
    pnl = [sign*(s["mc"]-s["o"]) for s in g]
    w = sum(1 for x in pnl if x > 0)
    lo, hi = prop_ci(w, len(g))
    print(f"{nm:<26}{len(g):>4}{w/len(g)*100:>7.0f}%{f'[{lo:.0f},{hi:.0f}]':>16}"
          f"{st.median(pnl):>10.1f}{sum(pnl)/len(pnl):>10.1f}")
allpnl = [(1 if s["o"] > s["f930"] else -1)*(s["mc"]-s["o"]) for s in S]
w = sum(1 for x in allpnl if x > 0)
lo, hi = prop_ci(w, len(S))
print(f"{'合计（双向都做）':<24}{len(S):>4}{w/len(S)*100:>7.0f}%{f'[{lo:.0f},{hi:.0f}]':>16}"
      f"{st.median(allpnl):>10.1f}{sum(allpnl)/len(allpnl):>10.1f}")
print(f"{'对照：无条件做多':<24}{len(S):>4}{base_up/len(S)*100:>7.0f}%{'':>16}"
      f"{st.median(s['mc']-s['o'] for s in S):>10.1f}"
      f"{sum(s['mc']-s['o'] for s in S)/len(S):>10.1f}")

# ---------- 规则 2：加距离过滤 ----------
print("\n" + "="*78)
print("规则2 · 同上 + |开盘-flip| 距离过滤")
print("="*78)
print(f"{'距离档':<18}{'n':>4}{'胜率':>8}{'95%区间':>16}{'中位R点':>10}{'均值R点':>10}")
for lo_, hi_, nm in [(0, 10, "<10点"), (10, 25, "10-25点"), (25, 50, "25-50点"), (50, 9e9, ">50点")]:
    g = [s for s in S if lo_ <= abs(s["o"]-s["f930"]) < hi_]
    if len(g) < 4: continue
    pnl = [(1 if s["o"] > s["f930"] else -1)*(s["mc"]-s["o"]) for s in g]
    w = sum(1 for x in pnl if x > 0)
    a, b = prop_ci(w, len(g))
    print(f"{nm:<18}{len(g):>4}{w/len(g)*100:>7.0f}%{f'[{a:.0f},{b:.0f}]':>16}"
          f"{st.median(pnl):>10.1f}{sum(pnl)/len(pnl):>10.1f}")

# ---------- 规则 3：盘前 heatmap 的翻转点密度当「真空/走廊」用 ----------
print("\n" + "="*78)
print("规则3 · 盘前 heatmap 结构：开盘价上下 25 点内的符号翻转点个数 → 当天早盘振幅")
print("="*78)
print(f"{'翻转点密度':<20}{'n':>4}{'早盘振幅中位':>14}{'早盘|位移|中位':>16}")
for lo_, hi_, nm in [(0, 1, "0个(单一结构)"), (1, 3, "1-2个"), (3, 99, "3个以上(碎)")]:
    g = [s for s in S if lo_ <= sum(1 for c in s["pre_cross"] if abs(c-s["o"]) <= 25) < hi_]
    if len(g) < 4: continue
    print(f"{nm:<20}{len(g):>4}{st.median(s['mh']-s['ml'] for s in g):>14.1f}"
          f"{st.median(abs(s['mc']-s['o']) for s in g):>16.1f}")

# ---------- 规则 4：止损/目标 —— 用 flip 当止损位是否合理 ----------
print("\n" + "="*78)
print("规则4 · 用 9:30 flip 当止损位：先触止损 vs 先到目标（目标=止损距离×2）")
print("="*78)
res = {"先止损": 0, "先到目标": 0, "都没到": 0}
rr = []
for s in S:
    d = s["o"] - s["f930"]
    if abs(d) < 3 or abs(d) > 40: continue
    long = d > 0
    stop = s["f930"]
    risk = abs(d)
    tgt = s["o"] + (2*risk if long else -2*risk)
    hit = None
    for b in s["m"]:
        lo_, hi_ = b["low"], b["high"]
        s_hit = lo_ <= stop if long else hi_ >= stop
        t_hit = hi_ >= tgt if long else lo_ <= tgt
        if s_hit and t_hit: hit = "先止损"; break     # 同K保守判定
        if s_hit: hit = "先止损"; break
        if t_hit: hit = "先到目标"; break
    res[hit or "都没到"] += 1
    if hit == "先到目标": rr.append(2.0)
    elif hit == "先止损": rr.append(-1.0)
    else: rr.append(((s["mc"]-s["o"])/risk) * (1 if long else -1))
n = sum(res.values())
if n:
    print(f"n={n}   先止损 {res['先止损']}({res['先止损']/n*100:.0f}%)   "
          f"先到目标 {res['先到目标']}({res['先到目标']/n*100:.0f}%)   "
          f"都没到 {res['都没到']}({res['都没到']/n*100:.0f}%)")
    print(f"总 R = {sum(rr):+.1f}R   平均 {sum(rr)/len(rr):+.2f}R/笔   中位 {st.median(rr):+.2f}R")
    print("→ 2R 目标 + flip 当止损，止损距离中位 "
          f"{st.median(abs(s['o']-s['f930']) for s in S if 3 <= abs(s['o']-s['f930']) <= 40):.0f} 点")
