#!/usr/bin/env python3
"""盘前 heatmap → 自算 flip → 建仓位置：全样本回测（含零模型对照）

无未来函数：每天只用 D-1 收盘那一帧的 per-strike GEX（= 盘前你在 heatmap 上看到的东西）
+ D 当天的开盘价，去预测 D 当天 9:30 之后的走势。
"""
import json, glob, os, random, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))
random.seed(20260804)
MORNING_END = 150          # 9:30 起第 150 根 = 12:00 ET（用户只做早盘）


# ---------- 基础工具 ----------
def crossings(strikes, net):
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0:
            continue
        out.append(strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0))
    return out


def est_flip(frame, ref):
    cs = crossings([r[0] for r in frame["s"]], [r[1]*1e3 for r in frame["s"]])
    return min(cs, key=lambda x: abs(x-ref)) if cs else None


def pos_nodes(frame, ref, side, topn=3):
    """ref 上方/下方按 netGex 绝对量级排序的正 gamma 节点（吸引子/目标位）"""
    rows = [(r[0], r[1]*1e3) for r in frame["s"] if r[1] > 0]
    rows = [r for r in rows if (r[0] > ref if side == "up" else r[0] < ref)]
    rows.sort(key=lambda r: -r[1])
    return rows[:topn]


def load_days():
    out = {}
    for p in sorted(glob.glob(f"{DIR}/day_*.json")):
        d = json.load(open(p))
        if d.get("bars"):
            out[d["date"]] = d
    return out


def load_strikes():
    out = {}
    for p in sorted(glob.glob(f"{DIR}/strikes/st_*.json")):
        d = json.load(open(p))
        if d.get("frames"):
            out[d["date"]] = d
    return out


# ---------- 组装样本 ----------
def build():
    days, strikes = load_days(), load_strikes()
    dates = sorted(set(days) & set(strikes))
    samples = []
    for i in range(1, len(dates)):
        D, P = dates[i], dates[i-1]
        # 交易日必须连续（P 是 D 的前一个有数据日）；跳空太久的不算
        prev = strikes[P]["frames"][-1]              # D-1 收盘帧 = D 盘前你看到的 heatmap
        prev_close = prev["spot"]
        bars = days[D]["bars"]
        if len(bars) < MORNING_END:
            continue
        o = bars[0]["open"]
        f_pc = est_flip(prev, prev_close)            # 用昨收当参考点
        f_op = est_flip(prev, o)                     # 用今开当参考点（盘前也知道）
        if f_pc is None or f_op is None:
            continue
        m = bars[:MORNING_END]
        samples.append({
            "date": D, "prev": P, "prev_close": prev_close, "open": o,
            "flip_pc": f_pc, "flip_op": f_op,
            "prev_tg": prev["tg"],                   # 昨收 totalGex（百万）
            "up_nodes": pos_nodes(prev, o, "up"), "dn_nodes": pos_nodes(prev, o, "dn"),
            "m_high": max(b["high"] for b in m), "m_low": min(b["low"] for b in m),
            "m_close": m[-1]["close"],
            "d_high": max(b["high"] for b in bars), "d_low": min(b["low"] for b in bars),
            "d_close": bars[-1]["close"],
            "bars": bars,
            # 当天真实的官方开盘首帧 flip（只用于「盘前估计准不准」这一项对照，不进策略）
            "true_open_flip": strikes[D]["frames"][0].get("flip"),
        })
    return samples


# ---------- A. 盘前估计 vs 当天实际 ----------
def part_a(S):
    print("\n" + "="*74)
    print("A · 盘前(D-1收盘帧)自算 flip  vs  D 当天开盘首帧官方 flip")
    print("="*74)
    ds = [(abs(s["flip_pc"]-s["true_open_flip"]), s) for s in S if s["true_open_flip"]]
    if not ds:
        print("无可对照样本"); return
    e = sorted(x[0] for x in ds)
    print(f"n={len(e)}  中位偏移={e[len(e)//2]:.2f}点  均值={sum(e)/len(e):.2f}  "
          f"<5点={sum(1 for x in e if x<5)/len(e)*100:.0f}%  "
          f"<10点={sum(1 for x in e if x<10)/len(e)*100:.0f}%  最大={e[-1]:.1f}")
    print("→ 盘前那张图算出来的 flip，隔夜到开盘会漂移这么多。这就是「盘前 flip」的精度上限。")


# ---------- B. 方向信号 ----------
def part_b(S):
    print("\n" + "="*74)
    print("B · 开盘价相对盘前自算 flip 的位置 → 当天/早盘方向")
    print("="*74)
    above = [s for s in S if s["open"] > s["flip_pc"]]
    below = [s for s in S if s["open"] < s["flip_pc"]]
    print(f"{'分组':<22}{'n':>4}{'早盘收涨%':>11}{'早盘中位幅度':>13}{'全天收涨%':>11}{'全天中位幅度':>13}")
    for name, g in [("开盘 > flip (正γ)", above), ("开盘 < flip (负γ)", below), ("全样本", S)]:
        if not g: continue
        mup = sum(1 for s in g if s["m_close"] > s["open"])/len(g)*100
        dup = sum(1 for s in g if s["d_close"] > s["open"])/len(g)*100
        mmv = st.median(s["m_close"]-s["open"] for s in g)
        dmv = st.median(s["d_close"]-s["open"] for s in g)
        print(f"{name:<22}{len(g):>4}{mup:>10.0f}%{mmv:>13.1f}{dup:>10.0f}%{dmv:>13.1f}")

    # 距离分档：贴着 flip 开 vs 远离 flip 开
    print(f"\n{'|开盘-flip| 分档':<22}{'n':>4}{'早盘收涨%':>11}{'早盘中位幅度':>13}{'早盘|振幅|中位':>15}")
    for lo, hi, nm in [(0, 5, "<5点(贴脸)"), (5, 15, "5-15点"), (15, 30, "15-30点"), (30, 9e9, ">30点")]:
        g = [s for s in S if lo <= abs(s["open"]-s["flip_pc"]) < hi]
        if not g: continue
        mup = sum(1 for s in g if s["m_close"] > s["open"])/len(g)*100
        mmv = st.median(s["m_close"]-s["open"] for s in g)
        rng = st.median(s["m_high"]-s["m_low"] for s in g)
        print(f"{nm:<22}{len(g):>4}{mup:>10.0f}%{mmv:>13.1f}{rng:>15.1f}")


# ---------- C. flip 当入场位：触及后的反应（带零模型） ----------
def touch_reaction(bars, level, start_i, horizon=30):
    """从 start_i 起找第一次触及 level 的分钟，返回触及后 horizon 分钟的位移"""
    for i in range(start_i, min(len(bars), MORNING_END)):
        b = bars[i]
        if b["low"] <= level <= b["high"]:
            j = min(i+horizon, len(bars)-1)
            return i, bars[j]["close"] - level
    return None, None


def part_c(S):
    print("\n" + "="*74)
    print("C · 把 flip 当入场位：价格触及后 30 分钟的位移（零模型 = 等距随机价位）")
    print("="*74)
    rows = {"flip_上方开": [], "flip_下方开": [], "随机_上方": [], "随机_下方": []}
    for s in S:
        d = s["flip_pc"] - s["open"]
        if abs(d) < 1 or abs(d) > 40:      # 太近没意义，太远当天够不着
            continue
        i, mv = touch_reaction(s["bars"], s["flip_pc"], 1)
        # 零模型：同样距离、同样方向，但是个随机价位（打散 ±40% 距离）
        rd = d * random.uniform(0.6, 1.4)
        i2, mv2 = touch_reaction(s["bars"], s["open"]+rd, 1)
        key = "flip_下方开" if d < 0 else "flip_上方开"     # flip 在开盘下方 = 回踩
        rkey = "随机_下方" if d < 0 else "随机_上方"
        if mv is not None: rows[key].append(mv)
        if mv2 is not None: rows[rkey].append(mv2)
    print(f"{'':<16}{'触及数':>7}{'触及后30分位移中位':>20}{'向上占比':>10}")
    for k, v in rows.items():
        if not v: continue
        up = sum(1 for x in v if x > 0)/len(v)*100
        print(f"{k:<16}{len(v):>7}{st.median(v):>20.2f}{up:>9.0f}%")
    print("→ 若 flip 行与随机位无差别，说明 flip 不是可交易的入场位，只是地图标记。")


# ---------- D. 上方大正节点当目标位 ----------
def part_d(S):
    print("\n" + "="*74)
    print("D · 盘前大正 gamma 节点当目标位：早盘触达率（零模型 = 等距随机价位）")
    print("="*74)
    hit, hitr, dists = 0, 0, []
    n = 0
    for s in S:
        if not s["up_nodes"]:
            continue
        k = s["up_nodes"][0][0]
        d = k - s["open"]
        if d <= 0 or d > 60:
            continue
        n += 1; dists.append(d)
        if s["m_high"] >= k: hit += 1
        rd = d * random.uniform(0.6, 1.4)
        if s["m_high"] >= s["open"]+rd: hitr += 1
    if n:
        print(f"n={n}  最大正节点中位距离={st.median(dists):.1f}点")
        print(f"早盘触达率：最大正节点 {hit/n*100:.0f}%   等距随机位 {hitr/n*100:.0f}%   "
              f"差值 {(hit-hitr)/n*100:+.0f}pp")
        print("→ 差值≈0 说明「节点是磁铁」在触达率上没有超额，只是距离效应。")


def main():
    S = build()
    print(f"样本：{len(S)} 个交易日  ({S[0]['date']} ~ {S[-1]['date']})" if S else "无样本")
    if not S: return
    part_a(S); part_b(S); part_c(S); part_d(S)


if __name__ == "__main__":
    main()
