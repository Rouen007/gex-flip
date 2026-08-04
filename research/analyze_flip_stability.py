#!/usr/bin/env python3
"""官方 flip 定义 = 「离现价最近的 netGex 符号翻转」→ 它会不会随 spot 移动而瞬移？
   并构造一个「稳定 flip」（最佳分隔位）做对照。"""
import json, glob, os, statistics as st

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))


def crossings(strikes, net):
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0:
            continue
        out.append(strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0))
    return out


def stable_flip(frame):
    """最佳分隔位：找一个分界 x，使「x 以下的负 gamma 量 + x 以上的正 gamma 量」最大。
       不依赖 spot，因此不会跟着价格瞬移。"""
    rows = sorted((r[0], r[1]*1e3) for r in frame["s"])
    ks = [r[0] for r in rows]; vs = [r[1] for r in rows]
    tot_pos = sum(v for v in vs if v > 0)
    best, best_x = None, None
    below_neg = 0.0; above_pos = tot_pos
    for i in range(len(ks)):
        # 分界放在 ks[i] 和 ks[i+1] 之间
        if vs[i] < 0: below_neg += -vs[i]
        else: above_pos -= vs[i]
        score = below_neg + above_pos
        x = (ks[i] + ks[i+1])/2 if i+1 < len(ks) else ks[i]
        if best is None or score > best:
            best, best_x = score, x
    return best_x


def main():
    files = sorted(glob.glob(f"{DIR}/strikes/st_*.json"))
    jumps_off, jumps_stb = [], []
    ncross, spread = [], []
    intraday_range_off, intraday_range_stb = [], []
    for p in files:
        d = json.load(open(p))
        fr = [f for f in d["frames"] if f.get("flip") is not None]
        if len(fr) < 10: continue
        offs = [f["flip"] for f in fr]
        stbs = [stable_flip(f) for f in fr]
        spots = [f["spot"] for f in fr]
        for i in range(1, len(fr)):
            ds = abs(spots[i]-spots[i-1])
            if ds > 8: continue                 # 只看 spot 基本没动的相邻帧
            jumps_off.append(abs(offs[i]-offs[i-1]))
            jumps_stb.append(abs(stbs[i]-stbs[i-1]))
        for f in fr:
            cs = crossings([r[0] for r in f["s"]], [r[1]*1e3 for r in f["s"]])
            if cs:
                ncross.append(len(cs))
                spread.append(max(cs)-min(cs))
        intraday_range_off.append(max(offs)-min(offs))
        intraday_range_stb.append(max(stbs)-min(stbs))

    print("="*72)
    print("官方 flip 的稳定性问题")
    print("="*72)
    print(f"每帧符号翻转点个数：中位 {st.median(ncross):.0f}  均值 {sum(ncross)/len(ncross):.1f}  "
          f"最大 {max(ncross)}")
    print(f"翻转点最高最低跨度：中位 {st.median(spread):.0f} 点")
    print("→ 一张 heatmap 上有一堆符号翻转点，官方只取「离现价最近的那个」。")
    print()
    print("相邻两帧 spot 变动 <8 点时，flip 自己跳了多少：")
    jo, js = sorted(jumps_off), sorted(jumps_stb)
    for nm, a in [("官方 flip(最近现价)", jo), ("稳定 flip(最佳分隔)", js)]:
        print(f"  {nm:<22} 中位 {a[len(a)//2]:6.2f} 点   >10点占比 {sum(1 for x in a if x>10)/len(a)*100:5.1f}%"
              f"   >30点占比 {sum(1 for x in a if x>30)/len(a)*100:5.1f}%")
    print()
    print(f"当天 flip 全天极差(高-低)：官方中位 {st.median(intraday_range_off):.0f} 点  "
          f"稳定版中位 {st.median(intraday_range_stb):.0f} 点")


if __name__ == "__main__":
    main()
