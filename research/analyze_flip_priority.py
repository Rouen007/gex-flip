#!/usr/bin/env python3
"""一列 heatmap 上有一堆符号翻转点 —— 哪个才该被叫做「the flip」？

官方规则是「取离现价最近」。本脚本把 5 种候选优先级放在一起，用**机制本身**当裁判：
flip 的全部理论主张是「上方=做市商 long gamma=波动被抑制 / 下方=short gamma=波动被放大」，
所以好的 flip 定义，应该能把「后续实际波动」分得最开。

评判三项：
  A 波动分离度 = 下方组后续5分钟真实波幅 ÷ 上方组（>1 才符合机制，越大越好）
  B 稳定性     = 现价基本没动时，这个定义自己跳多少（越小越好）
  C 样本平衡   = 上下方帧数是否极端失衡（失衡 = 这个定义没在描述现价附近的结构）
"""
import json, glob, os, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))
FWD_MS = 5*60*1000          # 前视窗口 5 分钟


# ══════════ 翻转点 + 5 种优先级 ══════════
def crossings(rows):
    """→ [(零点, 低档, 高档, 低值, 高值, 低档序号)]"""
    rows = sorted(rows)
    out = []
    for i in range(len(rows)-1):
        (k0, v0), (k1, v1) = rows[i], rows[i+1]
        if v0 == 0 or v1 == 0 or v0*v1 >= 0:
            continue
        out.append((k0 + (k1-k0)*(0-v0)/(v1-v0), k0, k1, v0, v1, i))
    return out


def pri_nearest(cs, rows, spot):
    """① 官方：离现价最近"""
    return min(cs, key=lambda c: abs(c[0]-spot))[0]


def pri_thickest(cs, rows, spot):
    """② 最厚：夹住它的两档量级最大"""
    return max(cs, key=lambda c: max(abs(c[3]), abs(c[4])))[0]


def pri_separator(cs, rows, spot):
    """③ 最佳分隔：让「下方负gamma总量 + 上方正gamma总量」最大"""
    rows = sorted(rows)
    best, bx = None, None
    for c in cs:
        x = c[0]
        s = sum(-v for k, v in rows if k < x and v < 0) + \
            sum(v for k, v in rows if k > x and v > 0)
        if best is None or s > best:
            best, bx = s, x
    return bx


def pri_deepest(cs, rows, spot):
    """④ 最深：两侧连续同号的档数最多（结构最干净的那道墙）"""
    rows = sorted(rows)
    vs = [v for _, v in rows]
    best, bx = None, None
    for c in cs:
        i = c[5]
        d = 0
        j = i
        while j >= 0 and vs[j]*vs[i] > 0:
            d += 1; j -= 1
        j = i+1
        while j < len(vs) and vs[j]*vs[i+1] > 0:
            d += 1; j += 1
        if best is None or d > best:
            best, bx = d, c[0]
    return bx


def pri_thick_near(cs, rows, spot):
    """⑤ 厚度×距离折中：只在「厚度≥全链最大节点5%」的翻转点里取最近"""
    mx = max(abs(v) for _, v in rows) or 1
    ok = [c for c in cs if max(abs(c[3]), abs(c[4])) >= mx*0.05]
    return min(ok or cs, key=lambda c: abs(c[0]-spot))[0]


PRIS = [("①最近现价(官方)", pri_nearest), ("②最厚", pri_thickest),
        ("③最佳分隔", pri_separator), ("④最深", pri_deepest),
        ("⑤厚度过滤后取最近", pri_thick_near)]


# ══════════ 组装 ══════════
def load():
    days = {}
    for p in sorted(glob.glob(f"{DIR}/day_*.json")):
        d = json.load(open(p))
        if d.get("bars"): days[d["date"]] = d["bars"]
    out = []
    for p in sorted(glob.glob(f"{DIR}/strikes/st_*.json")):
        d = json.load(open(p))
        if d["date"] not in days or not d.get("frames"):
            continue
        out.append((d["date"], d["frames"], days[d["date"]]))
    return out


def fwd_range(bars, t0):
    """t0 之后 5 分钟的真实波幅（最高-最低）"""
    seg = [b for b in bars if t0 <= b["time"] < t0+FWD_MS]
    if len(seg) < 3:
        return None
    return max(b["high"] for b in seg) - min(b["low"] for b in seg)


def main():
    data = load()
    if not data:
        print(f"没数据，检查 GEXFLIP_DATA={DIR}"); return

    above = {n: [] for n, _ in PRIS}
    below = {n: [] for n, _ in PRIS}
    jumps = {n: [] for n, _ in PRIS}
    ncross = []
    prev = {n: None for n, _ in PRIS}

    for date, frames, bars in data:
        t_open = bars[0]["time"]
        for n, _ in PRIS:
            prev[n] = None
        for f in frames:
            rows = [(r[0], r[1]*1e3) for r in f["s"]]
            spot, t = f["spot"], f["t"]
            # 排除开盘 30 分钟和收盘 30 分钟（波动的时段效应太强）
            mins = (t - t_open)/60000
            if not (30 <= mins <= 360):
                continue
            cs = crossings(rows)
            if not cs:
                continue
            ncross.append(len(cs))
            fr = fwd_range(bars, t)
            for n, fn in PRIS:
                try:
                    x = fn(cs, rows, spot)
                except Exception:
                    continue
                if x is None:
                    continue
                if prev[n] is not None and abs(spot-prev[n][1]) < 8:
                    jumps[n].append(abs(x-prev[n][0]))
                prev[n] = (x, spot)
                if fr is None:
                    continue
                (above if spot > x else below)[n].append(fr)

    print(f"样本 {len(data)} 天 / {len(ncross)} 帧（已剔开盘30分与收盘后段）")
    print(f"每帧翻转点个数：中位 {st.median(ncross):.0f}  均值 {sum(ncross)/len(ncross):.1f}  最多 {max(ncross)}")
    print("\n" + "="*88)
    print("哪种优先级最符合 flip 的机制主张？")
    print("="*88)
    print(f"{'优先级':<20}{'上方帧':>7}{'下方帧':>7}{'上方波幅':>10}{'下方波幅':>10}"
          f"{'A分离度':>10}{'B自跳中位':>11}")
    print("-"*88)
    res = []
    for n, _ in PRIS:
        a, b = above[n], below[n]
        if len(a) < 30 or len(b) < 30:
            print(f"{n:<20}{len(a):>7}{len(b):>7}   样本太失衡，跳过"); continue
        ma, mb = st.median(a), st.median(b)
        sep = mb/ma if ma else 0
        j = sorted(jumps[n])
        jm = j[len(j)//2] if j else float('nan')
        res.append((sep, n, jm))
        print(f"{n:<20}{len(a):>7}{len(b):>7}{ma:>10.2f}{mb:>10.2f}{sep:>10.2f}{jm:>11.2f}")

    print("\nA 分离度 = 下方组波幅 ÷ 上方组。>1 符合机制（下方 short gamma 放大波动），越大越好")
    print("B 自跳    = 现价变动<8点时该定义自己跳多少点，越小越稳")
    if res:
        res.sort(reverse=True)
        print(f"\n→ 分离度最好：{res[0][1]}（{res[0][0]:.2f}）"
              f"　最差：{res[-1][1]}（{res[-1][0]:.2f}）")

    # 官方定义单独看：分离度随「距 flip 远近」怎么变
    print("\n" + "="*88)
    print("官方定义：现价离 flip 越远，波动差异越明显？")
    print("="*88)
    buckets = {}
    for date, frames, bars in data:
        t_open = bars[0]["time"]
        for f in frames:
            rows = [(r[0], r[1]*1e3) for r in f["s"]]
            spot, t = f["spot"], f["t"]
            if not (30 <= (t-t_open)/60000 <= 360):
                continue
            cs = crossings(rows)
            if not cs:
                continue
            x = pri_nearest(cs, rows, spot)
            fr = fwd_range(bars, t)
            if fr is None:
                continue
            d = spot - x
            for lo, hi, nm in [(-9e9, -30, "下方>30点"), (-30, -10, "下方10-30"),
                               (-10, 0, "下方0-10"), (0, 10, "上方0-10"),
                               (10, 30, "上方10-30"), (30, 9e9, "上方>30点")]:
                if lo <= d < hi:
                    buckets.setdefault(nm, []).append(fr)
    order = ["下方>30点", "下方10-30", "下方0-10", "上方0-10", "上方10-30", "上方>30点"]
    print(f"{'现价相对 flip':<16}{'n':>6}{'后续5分波幅中位':>16}")
    for nm in order:
        v = buckets.get(nm, [])
        if len(v) < 30: continue
        print(f"{nm:<16}{len(v):>6}{st.median(v):>16.2f}")


if __name__ == "__main__":
    main()
