#!/usr/bin/env python3
"""「flip 下方波动更大」是真的 gamma 机制，还是只是「跌了的时候波动大」？

关键混淆：下跌日本来就波动大（杠杆效应），而价格跌下去自然就到了 flip 下方。
所以必须拿安慰剂位（placebo level）做对照 —— 如果「在当日开盘价下方」也能分出
同样的波动差，那 flip 就没提供 gamma 之外的任何信息。

对照组：
  · 当日开盘价     —— 纯「涨跌」代理，不含任何期权结构
  · 当日 VWAP 近似 —— 常用日内均衡位
  · King 行权价    —— 另一个 GEX 结构位（非 flip）
  · 随机位         —— 每天取一个和 flip 同等距离分布的随机价位
另加「同日内」检验：只比较同一天内上方帧 vs 下方帧，消掉日间波动率差异。
"""
import json, glob, os, random, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))
FWD_MS = 5*60*1000
random.seed(20260805)


def crossings(rows):
    rows = sorted(rows)
    out = []
    for i in range(len(rows)-1):
        (k0, v0), (k1, v1) = rows[i], rows[i+1]
        if v0 == 0 or v1 == 0 or v0*v1 >= 0:
            continue
        out.append(k0 + (k1-k0)*(0-v0)/(v1-v0))
    return out


def load():
    days, gex = {}, {}
    for p in sorted(glob.glob(f"{DIR}/day_*.json")):
        d = json.load(open(p))
        if d.get("bars"):
            days[d["date"]] = d
    for p in sorted(glob.glob(f"{DIR}/strikes/st_*.json")):
        d = json.load(open(p))
        if d.get("frames"):
            gex[d["date"]] = d["frames"]
    return [(dt, gex[dt], days[dt]) for dt in sorted(set(days) & set(gex))]


def fwd_range(bars, t0):
    seg = [b for b in bars if t0 <= b["time"] < t0+FWD_MS]
    return (max(b["high"] for b in seg) - min(b["low"] for b in seg)) if len(seg) >= 3 else None


def ratio(above, below):
    if len(above) < 30 or len(below) < 30:
        return None
    return st.median(below)/st.median(above)


def main():
    data = load()
    LV = ["flip", "开盘价", "VWAP近似", "King", "随机位"]
    A = {k: [] for k in LV}
    B = {k: [] for k in LV}
    # 同日内检验：每天各自算比值，再看跨日中位
    per_day = {k: [] for k in LV}

    for date, frames, day in data:
        bars = day["bars"]
        t_open = bars[0]["time"]
        o = bars[0]["open"]
        # King：用当日 gexSeries 的第一帧（9:30 可得，无未来函数）
        king = None
        if day.get("gexSeries"):
            king = day["gexSeries"][0].get("king")
        # 随机位：以开盘价为中心，取一个 ±(5~40) 点的随机偏移
        rnd = o + random.choice([-1, 1])*random.uniform(5, 40)
        dayA = {k: [] for k in LV}
        dayB = {k: [] for k in LV}
        cum_pv = cum_v = 0.0
        for f in frames:
            spot, t = f["spot"], f["t"]
            if not (30 <= (t-t_open)/60000 <= 360):
                continue
            cs = crossings([(r[0], r[1]*1e3) for r in f["s"]])
            if not cs:
                continue
            fl = min(cs, key=lambda x: abs(x-spot))
            fr = fwd_range(bars, t)
            if fr is None:
                continue
            # VWAP 近似：到当前为止所有已收 bar 的典型价均值（volume 全 0，用等权）
            seg = [b for b in bars if b["time"] <= t]
            vwap = sum((b["high"]+b["low"]+b["close"])/3 for b in seg)/len(seg) if seg else o
            levels = {"flip": fl, "开盘价": o, "VWAP近似": vwap,
                      "King": king, "随机位": rnd}
            for k, lv in levels.items():
                if lv is None or lv == 0:
                    continue
                (dayA if spot > lv else dayB)[k].append(fr)
        for k in LV:
            A[k] += dayA[k]; B[k] += dayB[k]
            if len(dayA[k]) >= 5 and len(dayB[k]) >= 5:
                per_day[k].append(st.median(dayB[k])/st.median(dayA[k]))

    print(f"样本 {len(data)} 天\n")
    print("="*84)
    print("「下方波动更大」是 flip 独有的，还是任何'跌破某位'都成立？")
    print("="*84)
    print(f"{'分界位':<12}{'上方帧':>7}{'下方帧':>7}{'上方波幅':>10}{'下方波幅':>10}"
          f"{'全样本比值':>11}{'同日内比值中位':>15}")
    print("-"*84)
    for k in LV:
        a, b = A[k], B[k]
        if len(a) < 30 or len(b) < 30:
            print(f"{k:<12}{len(a):>7}{len(b):>7}   样本不足"); continue
        pd = per_day[k]
        pdm = st.median(pd) if pd else float('nan')
        print(f"{k:<12}{len(a):>7}{len(b):>7}{st.median(a):>10.2f}{st.median(b):>10.2f}"
              f"{st.median(b)/st.median(a):>11.2f}{pdm:>15.2f}  (n={len(pd)}天)")

    print("\n比值 >1 = 该位下方波动更大。**同日内比值**消掉了日间波动率差异，是更干净的检验。")
    print("若 flip 与开盘价/VWAP 的比值差不多 → flip 没提供「跌了」之外的额外信息。")

    print("\n" + "="*84)
    print("关键诊断：这个「上方/下方」到底是日内分类还是日间分类？")
    print("="*84)
    for k in LV:
        n_both = len(per_day[k])
        print(f"  {k:<12} 全天在同一侧的日子 {len(data)-n_both:>3}/{len(data)}"
              f"　两侧都待过的 {n_both:>3} 天")
    print("\n→ 若绝大多数日子全天只待在一侧，那「flip 上方 vs 下方」本质是在给**整天**分类，")
    print("  跟「今天是涨日还是跌日」高度共线，不是在描述日内的 gamma 状态切换。")


if __name__ == "__main__":
    main()
