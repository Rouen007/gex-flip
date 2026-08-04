#!/usr/bin/env python3
"""
gex-flip · 从 heatmap 的 per-strike GEX 推算 Gamma Flip（个股 / ETF / 指数通用）

算法（SPX 60天/4677帧 + 10只个股23组到期，100% 精确复现官方 gammaFlip，零偏差）：
    1. 取一列（一个到期日 expiryGroup）的 (行权价, netGex)，按行权价升序
    2. 找相邻两档之间 netGex 符号翻转的位置，线性插值：
         x = K低 + (K高−K低) × |netGex低| / (|netGex低| + |netGex高|)
    3. 多个零点时，取「离当前现价最近」的那一个 = flip
    ⛔ 不是累加和(cumsum)穿零 —— 那个口径 SPX 上中位误差 19.16 点、复现率 0%

用法：
    python3 flip.py TSLA                 # 拉实时数据，出 flip + 质量评分
    python3 flip.py TSLA NVDA AAPL       # 批量
    python3 flip.py TSLA --chart         # 额外画出终端版 heatmap 列（对着图核对用）
    python3 flip.py --manual 315:-83.8 317.5:300.6 --spot 323.45
                                         # 只有截图没有接口时，手敲两档值算
"""
import json, subprocess, os, sys, datetime as dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

BR = os.path.expanduser("~/.npm-global/bin/opencli")
SESSION = os.environ.get("YHS_SESSION", "svb6mefm")
WIDTH = 34


# ══════════════════ 核心算法 ══════════════════
def crossings(rows):
    """rows=[(strike, netGex)] → [(零点, 低档, 高档, 低值, 高值, 方向)]"""
    rows = sorted(rows)
    out = []
    for i in range(len(rows)-1):
        (k0, v0), (k1, v1) = rows[i][:2], rows[i+1][:2]
        if v0 == 0 or v1 == 0 or v0*v1 >= 0:
            continue
        x = k0 + (k1-k0)*(0-v0)/(v1-v0)
        out.append((x, k0, k1, v0, v1, "up" if v0 < 0 else "dn"))
    return out


def flip_of(rows, spot):
    """主函数：返回 (flip值, 全部翻转点)"""
    cs = crossings(rows)
    if not cs:
        return None, []
    return min(cs, key=lambda c: abs(c[0]-spot)), cs


def quality(rows, cs_best, spot):
    """flip 可信度：厚度 / 分辨率 / 瞬移距离 / 稳健重算"""
    nz = [r for r in rows if r[1] != 0]
    mx = max(abs(v) for _, v in nz) if nz else 1
    x, k0, k1, v0, v1, _ = cs_best
    thick = max(abs(v0), abs(v1))/mx*100
    step = k1-k0
    allc = [c[0] for c in crossings(rows)]
    others = [c for c in allc if abs(c-x) > 1e-9]
    jump = min((abs(c-x) for c in others), default=None)
    rob_rows = [(k, v) for k, v in nz if abs(v) >= mx*0.05]
    rc = crossings(rob_rows)
    rob = min((c[0] for c in rc), key=lambda z: abs(z-spot)) if rc else None
    return dict(thick=thick, step=step, step_pct=step/spot*100,
                jump=jump, jump_pct=(jump/spot*100 if jump else None),
                robust=rob, ncross=len(allc))


def verdict(q):
    t = q["thick"]
    if t >= 20: return "厚 —— 可信"
    if t >= 5:  return "中等 —— 能用但别当精确位"
    return "薄 ⚠️ 由小单撑起来的，是噪音不是位"


# ══════════════════ 取数 ══════════════════
def fetch(t):
    js = f'''(async()=>{{
      await fetch("/api/auth/refresh",{{method:"POST"}});
      const j=await fetch("/api/gex/intraday-history?ticker={t}&expiryGroup=1dte&bucket=5m&session=today&profile=standardGexOverlay").then(r=>r.json());
      if(!j.success) return JSON.stringify({{ok:false,err:JSON.stringify(j).slice(0,150)}});
      const p=j.data.latestPayload; const g={{}};
      for(const[k,v]of Object.entries(p.expiryGroups||{{}}))
        g[k]={{flip:(v.summary||{{}}).gammaFlip, sum:v.summary,
              s:(v.strikes||[]).map(x=>[x.strike,x.netGex,x.callOi,x.putOi])}};
      return JSON.stringify({{ok:true,spot:p.spot,state:p.state,stale:p.isStale,
                             reason:p.staleReason,updated:p.lastUpdated,
                             session:j.data.sessionDate,g:g}});
    }})()'''
    try:
        r = subprocess.run([BR, "browser", SESSION, "eval", js],
                           capture_output=True, text=True, timeout=200)
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": "opencli 超时"}
    s, e = r.stdout.find('{'), r.stdout.rfind('}')+1
    if s < 0:
        return {"ok": False, "err": "浏览器会话没返回 —— 先确认 Chrome 开着 yehangshe 且已登录"}
    d = json.loads(r.stdout[s:e])
    return json.loads(d) if isinstance(d, str) else d


def ensure_page():
    """确保浏览器会话停在已登录的站内页"""
    try:
        r = subprocess.run([BR, "browser", SESSION, "state"],
                           capture_output=True, text=True, timeout=60)
        if "yehangshe" in r.stdout:
            return True
        subprocess.run([BR, "browser", SESSION, "open",
                        "https://yehangshe.com/app/dashboard"],
                       capture_output=True, text=True, timeout=120)
        import time; time.sleep(8)
        return True
    except Exception:
        return False


# ══════════════════ 输出 ══════════════════
def draw(rows, spot, f, step_hint):
    nz = sorted([r for r in rows if r[1] != 0])
    if len(nz) < 3: return
    idx = min(range(len(nz)), key=lambda i: abs(nz[i][0]-spot))
    win = nz[max(0, idx-10): idx+11]
    mx = max(abs(r[1]) for r in win) or 1
    print(f"    {'行权价':>9} {'netGex':>11}  {'图上颜色':<9} {'条形 负←|→正':<{WIDTH+2}}")
    print("    " + "-"*66)
    prev = None
    for r in reversed(win):
        k, nv = r[0], r[1]
        n = max(1, int(abs(nv)/mx*WIDTH/2))
        bar = (" "*(WIDTH//2) + "█"*n) if nv > 0 else (" "*(WIDTH//2-n) + "█"*n)
        col = "橙/黄 正" if nv > 0 else "深紫 负"
        if prev is not None and prev*nv < 0 and f is not None and \
           min(k, prevk) <= f <= max(k, prevk):
            print(f"    {'':>9} {'':>11}  {'─'*(WIDTH+11)}  ← FLIP = {f:.2f}")
        star = " ◄现价" if abs(k-spot) <= step_hint/2 else ""
        print(f"    {k:>9} {nv/1e6:>10.1f}M  {col:<9} {bar:<{WIDTH+2}}{star}")
        prev, prevk = nv, k


def report(t, chart=False, exp=None):
    d = fetch(t)
    if not d.get("ok"):
        print(f"\n{t}: 取数失败 —— {d.get('err')}")
        return
    spot = d["spot"]
    ts = dt.datetime.fromtimestamp(d["updated"]/1000, ET).strftime("%m-%d %H:%M:%S ET")
    flag = f"⚠️ 陈旧({d.get('reason') or d.get('state')})" if d.get("stale") else "新鲜"
    print("\n" + "="*72)
    print(f"{t}   现价 {spot}   数据 {ts} {flag}   session {d.get('session')}")
    print("="*72)
    if exp and exp not in {k.lower() for k in d["g"]}:
        print(f" ⚠️ 该标的今天没有 {exp} 到期组（可用：{', '.join(d['g'])}）——"
              f"个股通常只有周五才有 0dte（末日），这不是 bug")
        return
    for g, v in d["g"].items():
        if exp and g.lower() != exp:
            continue
        rows = [(r[0], r[1]) for r in v["s"]]
        best, cs = flip_of(rows, spot)
        if best is None:
            print(f"\n 【{g}】 没有符号翻转点 → 该到期结构是单向的，flip 不存在")
            continue
        x, k0, k1, v0, v1, _ = best
        q = quality(rows, best, spot)
        off = v.get("flip")
        chk = f"  官方 {off:.2f} 偏差 {abs(x-off):.4f}" if off is not None else "  (无官方值可对)"
        print(f"\n 【{g}】 flip = {x:.2f}   ({(x-spot)/spot*100:+.2f}% vs 现价){chk}")
        print(f"    夹住它的两档：{k0} ({v0/1e6:+.1f}M)  ↔  {k1} ({v1/1e6:+.1f}M)")
        print(f"    手算：{k0} + ({k1}−{k0}) × {abs(v0)/1e6:.1f} / "
              f"({abs(v0)/1e6:.1f}+{abs(v1)/1e6:.1f}) = {x:.2f}")
        print(f"    厚度 {q['thick']:.1f}% → {verdict(q)}")
        print(f"    分辨率上限 一档 {q['step']} = 现价的 {q['step_pct']:.2f}%"
              f"（个股别报小数点）")
        if q["jump_pct"] is not None:
            risk = "⚠️ 灾难级" if q["jump_pct"] > 5 else "偏大" if q["jump_pct"] > 2 else "可控"
            print(f"    瞬移风险 次近翻转点距 {q['jump_pct']:.2f}% 价格 → {risk}"
                  f"（共 {q['ncross']} 个翻转点）")
        if q["robust"] is None:
            print(f"    ⚠️ 稳健检验：只留量级≥最大节点5%的档后**翻转点消失** "
                  f"→ 这个 flip 是假位，结构其实单向")
        elif abs(q["robust"]-x)/spot*100 > 1:
            print(f"    ⚠️ 稳健检验：过滤小单后 flip 跑到 {q['robust']:.2f}"
                  f"（差 {abs(q['robust']-x)/spot*100:.2f}%）→ 原值不稳")
        else:
            print(f"    稳健检验：过滤小单后 {q['robust']:.2f}，一致 ✓")
        sm = v.get("sum") or {}
        if sm:
            print(f"    旁证：King={sm.get('kingStrike')} CallWall={sm.get('callWallStrike')} "
                  f"PutWall={sm.get('putWallStrike')} TotalGEX={sm.get('totalGex',0)/1e9:.1f}B")
        print(f"    制度：现价 {'在 flip 上方 → 做市商净 long gamma → 高抛低吸 → 波动被抑制' if spot > x else '在 flip 下方 → 做市商净 short gamma → 追涨杀跌 → 波动被放大'}")
        if chart:
            print()
            draw(rows, spot, x, q["step"])


def manual(pairs, spot):
    rows = []
    for p in pairs:
        k, v = p.split(":")
        rows.append((float(k), float(v)*1e6))
    best, cs = flip_of(rows, spot)
    if best is None:
        print("这些档里没有符号翻转 —— 再往现价两边多读几档"); return
    x, k0, k1, v0, v1, _ = best
    print(f"\nflip = {x:.2f}   ({(x-spot)/spot*100:+.2f}% vs 现价 {spot})")
    print(f"手算：{k0} + ({k1}−{k0}) × {abs(v0)/1e6:.1f} / "
          f"({abs(v0)/1e6:.1f}+{abs(v1)/1e6:.1f}) = {x:.2f}")
    print(f"⚠️ 手敲模式没有全链数据，算不了厚度和瞬移风险 —— 只有 flip 的位置")


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--manual" in a:
        i = a.index("--manual")
        sp = float(a[a.index("--spot")+1]) if "--spot" in a else None
        pr = [x for x in a[i+1:] if ":" in x]
        if not sp or not pr:
            print("用法: flip.py --manual 315:-83.8 317.5:300.6 --spot 323.45"); sys.exit(1)
        manual(pr, sp); sys.exit(0)
    chart = "--chart" in a
    exp = None
    if "--exp" in a:                       # 只看某一个到期列，如 --exp 0dte（末日）
        i = a.index("--exp")
        if i+1 >= len(a):
            print("用法: flip.py SPX --exp 0dte"); sys.exit(1)
        exp = a[i+1].lower()
        del a[i:i+2]
    ts = [x.upper() for x in a if not x.startswith("--")]
    if not ts:
        print(__doc__); sys.exit(0)
    ensure_page()
    for t in ts:
        report(t, chart, exp)
