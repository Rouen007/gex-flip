#!/usr/bin/env python3
"""深挖唯一单调的发现：盘前 heatmap 在开盘价附近的「符号翻转点密度」→ 当天走势性质。
   用 趋势度 = |净位移| / 振幅 归一化掉波动率，并做置换检验。"""
import json, glob, os, random, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))
MEND = 150
random.seed(20260804)


def crossings(strikes, net):
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0: continue
        out.append(strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0))
    return out


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
    prev = strikes[P]["frames"][-1]
    cs = crossings([r[0] for r in prev["s"]], [r[1]*1e3 for r in prev["s"]])
    if not cs: continue
    o = bars[0]["open"]; m = bars[:MEND]
    mh, ml, mc = max(b["high"] for b in m), min(b["low"] for b in m), m[-1]["close"]
    rng = mh-ml
    if rng <= 0: continue
    S.append(dict(date=D, o=o, mc=mc, rng=rng, disp=abs(mc-o), trend=abs(mc-o)/rng,
                  dc=bars[-1]["close"],
                  n25=sum(1 for c in cs if abs(c-o) <= 25),
                  n50=sum(1 for c in cs if abs(c-o) <= 50),
                  ncross=len(cs)))

print(f"样本 {len(S)} 天\n")
print("="*78)
print("盘前翻转点密度（开盘价 ±25 点内） → 早盘走势性质")
print("="*78)
print(f"{'密度':<16}{'n':>4}{'振幅中位':>10}{'净位移中位':>12}{'趋势度中位':>12}{'趋势度均值':>12}")
groups = []
for lo, hi, nm in [(0, 1, "0个"), (1, 3, "1-2个"), (3, 99, "≥3个")]:
    g = [s for s in S if lo <= s["n25"] < hi]
    if len(g) < 4: continue
    groups.append((nm, g))
    print(f"{nm:<16}{len(g):>4}{st.median(s['rng'] for s in g):>10.1f}"
          f"{st.median(s['disp'] for s in g):>12.1f}"
          f"{st.median(s['trend'] for s in g):>12.3f}"
          f"{sum(s['trend'] for s in g)/len(g):>12.3f}")

# 置换检验：低密度组 vs 高密度组 的趋势度均值差
lowg = [s["trend"] for s in S if s["n25"] == 0]
higg = [s["trend"] for s in S if s["n25"] >= 3]
if lowg and higg:
    obs = sum(higg)/len(higg) - sum(lowg)/len(lowg)
    pool = lowg + higg
    cnt = 0; N = 20000
    for _ in range(N):
        random.shuffle(pool)
        a = pool[:len(higg)]; b = pool[len(higg):]
        if sum(a)/len(a) - sum(b)/len(b) >= obs: cnt += 1
    print(f"\n置换检验（≥3个 vs 0个 的趋势度均值差）：观测 {obs:+.3f}   "
          f"p = {cnt/N:.3f}   n={len(higg)}/{len(lowg)}")

# 单调性：Spearman 相关
def spearman(xs, ys):
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0]*len(v)
        for pos, i in enumerate(s): r[i] = pos+1
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs); mx = sum(rx)/n; my = sum(ry)/n
    num = sum((a-mx)*(b-my) for a, b in zip(rx, ry))
    den = (sum((a-mx)**2 for a in rx)*sum((b-my)**2 for b in ry))**0.5
    return num/den if den else 0

print(f"\nSpearman 相关（±25点翻转点数 vs 早盘趋势度）: {spearman([s['n25'] for s in S], [s['trend'] for s in S]):+.3f}")
print(f"Spearman 相关（±25点翻转点数 vs 早盘振幅）  : {spearman([s['n25'] for s in S], [s['rng'] for s in S]):+.3f}")
print(f"Spearman 相关（±50点翻转点数 vs 早盘趋势度）: {spearman([s['n50'] for s in S], [s['trend'] for s in S]):+.3f}")
print(f"Spearman 相关（全图翻转点总数 vs 早盘趋势度）: {spearman([s['ncross'] for s in S], [s['trend'] for s in S]):+.3f}")

# 时间稳定性：前后半段分开
h = len(S)//2
print("\n=== 前后半段稳定性（趋势度均值） ===")
print(f"{'':<16}{'前半段':>18}{'后半段':>18}")
for nm, sel in [("0个", lambda s: s["n25"] == 0), ("1-2个", lambda s: 1 <= s["n25"] <= 2),
                ("≥3个", lambda s: s["n25"] >= 3)]:
    a = [s["trend"] for s in S[:h] if sel(s)]
    b = [s["trend"] for s in S[h:] if sel(s)]
    fa = f"{sum(a)/len(a):.3f} (n={len(a)})" if a else "—"
    fb = f"{sum(b)/len(b):.3f} (n={len(b)})" if b else "—"
    print(f"{nm:<16}{fa:>18}{fb:>18}")
