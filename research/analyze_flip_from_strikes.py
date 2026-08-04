#!/usr/bin/env python3
"""从 per-strike GEX（= heatmap 一列）反算 gamma flip，并验证是否复现官方 gammaFlip。

结论（本脚本用来复现）：
  flip = 相邻两个行权价之间 netGex 由负转正 / 由正转负的线性插值零点，
         多个零点时取「离当前 spot 最近」的那个。
  ⚠️ 不是累加和(cumsum)穿零 —— 那个口径中位误差 19 点，完全错。
"""
import json, glob, os, sys

DIR = os.environ.get("GEXFLIP_DATA",
                     os.path.expanduser("~/trading-reports/nightwatch_replay_dataset"))


def load(date):
    p = f"{DIR}/strikes/st_{date}.json"
    return json.load(open(p)) if os.path.exists(p) else None


def crossings(strikes, net):
    """相邻 strike 间 netGex 符号翻转的线性插值零点 -> [(x, 'up'|'dn')]"""
    out = []
    for i in range(len(strikes)-1):
        y0, y1 = net[i], net[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0:
            continue
        x = strikes[i] + (strikes[i+1]-strikes[i]) * (0-y0)/(y1-y0)
        out.append((x, "up" if y0 < 0 else "dn"))
    return out


def est_flip(frame, spot=None):
    """给一帧 heatmap 数据算 flip。spot 缺省用帧内 spot。"""
    st = [r[0] for r in frame["s"]]
    net = [r[1]*1e3 for r in frame["s"]]
    sp = spot if spot is not None else frame["spot"]
    cs = crossings(st, net)
    if not cs:
        return None
    return min((c[0] for c in cs), key=lambda x: abs(x-sp))


def main():
    files = sorted(glob.glob(f"{DIR}/strikes/st_*.json"))
    if not files:
        print("没有 strikes/st_*.json，先跑 harvest_strikes.sh"); return
    tot = exact = 0
    worst = []
    per_day = []
    for p in files:
        d = json.load(open(p))
        errs = []
        for f in d["frames"]:
            if f.get("flip") is None:
                continue
            e = est_flip(f)
            if e is None:
                continue
            err = abs(e - f["flip"])
            errs.append(err); tot += 1
            if err < 0.01: exact += 1
            worst.append((err, d["date"], f["spot"], f["flip"], e))
        if errs:
            errs.sort()
            per_day.append((d["date"], len(errs), errs[len(errs)//2], max(errs)))
    print(f"=== flip 复现验证：{len(files)} 天 / {tot} 帧 ===")
    print(f"精确复现(<0.01点)：{exact}/{tot} = {exact/tot*100:.2f}%")
    worst.sort(reverse=True)
    print("\n误差最大的 10 帧：")
    print(f"{'误差':>9} {'日期':>12} {'spot':>9} {'官方flip':>11} {'自算flip':>11}")
    for err, dt, sp, off, e in worst[:10]:
        print(f"{err:9.3f} {dt:>12} {sp:9.2f} {off:11.3f} {e:11.3f}")
    bad = [x for x in per_day if x[3] > 0.01]
    print(f"\n有偏差的日子：{len(bad)}/{len(per_day)}")
    for dt, n, med, mx in bad[:15]:
        print(f"  {dt}  n={n:3d} 中位={med:.3f} 最大={mx:.3f}")


if __name__ == "__main__":
    main()
