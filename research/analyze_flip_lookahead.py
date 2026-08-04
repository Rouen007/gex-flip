#!/usr/bin/env python3
"""同一条「价格在 flip 上方 vs 下方」规则，用三种取值时点分别检验：
   ① D-1 收盘帧（盘前可得，无未来函数）
   ② D 当天 9:30 首帧（开盘可得，对当天剩余时间无未来函数）
   ③ D 当天收盘帧（⚠️ 未来函数，收盘才知道）
   如果只有 ③ 显著，那条老规律就是未来函数产物。"""
import json, glob, os

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))


def crossings(strikes, net):
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0: continue
        out.append(strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0))
    return out


def est(frame, ref):
    cs = crossings([r[0] for r in frame["s"]], [r[1]*1e3 for r in frame["s"]])
    return min(cs, key=lambda x: abs(x-ref)) if cs else None


days, strikes = {}, {}
for p in sorted(glob.glob(f"{DIR}/day_*.json")):
    d = json.load(open(p))
    if d.get("bars"): days[d["date"]] = d
for p in sorted(glob.glob(f"{DIR}/strikes/st_*.json")):
    d = json.load(open(p))
    if d.get("frames"): strikes[d["date"]] = d

dates = sorted(set(days) & set(strikes))
rows = []
for i in range(1, len(dates)):
    D, P = dates[i], dates[i-1]
    bars = days[D]["bars"]
    if len(bars) < 300: continue
    o, c = bars[0]["open"], bars[-1]["close"]
    fr = strikes[D]["frames"]
    f_pre = est(strikes[P]["frames"][-1], strikes[P]["frames"][-1]["spot"])   # ① 盘前
    f_open = fr[0].get("flip")                                               # ② 开盘首帧
    f_close = fr[-1].get("flip")                                             # ③ 收盘帧(未来函数)
    if None in (f_pre, f_open, f_close): continue
    rows.append(dict(date=D, o=o, c=c, up=c > o, f_pre=f_pre, f_open=f_open, f_close=f_close))

print(f"样本 {len(rows)} 天   基准收涨率 {sum(1 for r in rows if r['up'])/len(rows)*100:.0f}%\n")
print(f"{'flip 取值时点':<34}{'上方n':>6}{'上方收涨%':>11}{'下方n':>6}{'下方收涨%':>11}{'区分度':>9}")
specs = [
    ("① D-1收盘帧 vs 今开 (盘前可用)",      lambda r: (r["o"], r["f_pre"])),
    ("② D 9:30首帧 vs 今开 (开盘可用)",     lambda r: (r["o"], r["f_open"])),
    ("③ D 收盘帧 vs 今收 (⚠️未来函数)",     lambda r: (r["c"], r["f_close"])),
    ("④ D 收盘帧 vs 今开 (⚠️半未来函数)",   lambda r: (r["o"], r["f_close"])),
]
for name, get in specs:
    a = [r for r in rows if get(r)[0] > get(r)[1]]
    b = [r for r in rows if get(r)[0] < get(r)[1]]
    if not a or not b: continue
    pa = sum(1 for r in a if r["up"])/len(a)*100
    pb = sum(1 for r in b if r["up"])/len(b)*100
    print(f"{name:<34}{len(a):>6}{pa:>10.0f}%{len(b):>6}{pb:>10.0f}%{pa-pb:>8.0f}pp")

print("\n注：区分度 = 上方组收涨率 − 下方组收涨率。仅 ③④ 高 ⇒ 老规律是未来函数产物。")
