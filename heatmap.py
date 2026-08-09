#!/usr/bin/env python3
"""
读 yehangshe Dealer GEX Heatmap（/app/dealer-heatmap）—— 支持全市场标的，
不受 Standard GEX 那 11 个白名单限制。

⚠️ 口径警告：这里是 **Dealer GEX**（做市商一方），与 flip.py 用的 Standard GEX
   不是一回事，量级差几个数量级，**官方没有为它发布 gammaFlip，所以本脚本算出的
   "分界位" 没有官方值可对答案**（flip.py 那套是 100% 复现验证过的，这套不是）。

用法：
    python3 heatmap.py INTC PANW          # 按到期列 + 全列合计读结构
    python3 heatmap.py INTC --chart       # 附终端热力图
"""
import json, subprocess, os, sys

BR = os.path.expanduser("~/.npm-global/bin/opencli")
SESSION = os.environ.get("YHS_SESSION", "svb6mefm")


def crossings(rows):
    rows = sorted(rows)
    out = []
    for i in range(len(rows)-1):
        (k0, v0), (k1, v1) = rows[i], rows[i+1]
        if v0 == 0 or v1 == 0 or v0*v1 >= 0:
            continue
        out.append((k0 + (k1-k0)*(0-v0)/(v1-v0), k0, k1, v0, v1))
    return out


def boundary(rows, spot):
    cs = crossings(rows)
    return (min(cs, key=lambda c: abs(c[0]-spot)), cs) if cs else (None, [])


def fetch(t):
    js = f'''(async()=>{{
      await fetch("/api/auth/refresh",{{method:"POST"}});
      const j=await fetch("/api/dealer-heatmap/latest?ticker={t}").then(r=>r.json());
      if(!j.success) return JSON.stringify({{ok:false,err:JSON.stringify(j.error||{{}}).slice(0,150)}});
      const d=j.data;
      return JSON.stringify({{ok:true,ticker:d.ticker,spot:d.spot,state:d.state,
        market:d.marketStatus,session:d.sessionDateEt,gen:d.generatedAt,
        exps:d.expirations,strikes:d.strikes,cells:d.cells,rows:d.rowStacks}});
    }})()'''
    r = subprocess.run([BR, "browser", SESSION, "eval", js],
                       capture_output=True, text=True, timeout=240)
    s, e = r.stdout.find('{'), r.stdout.rfind('}')+1
    if s < 0:
        return {"ok": False, "err": "浏览器会话没返回（确认已登录 yehangshe）"}
    d = json.loads(r.stdout[s:e])
    return json.loads(d) if isinstance(d, str) else d


def std_flip(t):
    """拉 Standard GEX（白名单 11 个标的）的官方 gammaFlip —— 唯一经过验证的那个值"""
    js = f'''(async()=>{{
      const j=await fetch("/api/gex/intraday-history?ticker={t}&expiryGroup=1dte&bucket=5m&session=today&profile=standardGexOverlay").then(r=>r.json());
      if(!j.success) return JSON.stringify({{ok:false}});
      const p=j.data.latestPayload; const g={{}};
      for(const[k,v]of Object.entries(p.expiryGroups||{{}})) g[k]={{flip:(v.summary||{{}}).gammaFlip}};
      return JSON.stringify({{ok:true,spot:p.spot,g:g}});
    }})()'''
    try:
        r = subprocess.run([BR, "browser", SESSION, "eval", js],
                           capture_output=True, text=True, timeout=180)
        s, e = r.stdout.find('{'), r.stdout.rfind('}')+1
        if s < 0:
            return {"ok": False}
        d = json.loads(r.stdout[s:e])
        return json.loads(d) if isinstance(d, str) else d
    except Exception:
        return {"ok": False}


def ensure_page():
    r = subprocess.run([BR, "browser", SESSION, "state"],
                       capture_output=True, text=True, timeout=60)
    if "yehangshe" not in r.stdout:
        subprocess.run([BR, "browser", SESSION, "open",
                        "https://yehangshe.com/app/dealer-heatmap"],
                       capture_output=True, text=True, timeout=120)
        import time; time.sleep(9)


def report(t, chart=False, near=12):
    d = fetch(t)
    if not d.get("ok"):
        print(f"\n{t}: 取数失败 —— {d.get('err')}"); return
    spot = d["spot"]
    print("\n" + "="*78)
    print(f"{t}   现价 {spot}   {d['session']}   市场 {d['market']}   数据状态 {d['state']}"
          + ("  ⚠️" if d["state"] != "fresh" else ""))
    print("="*78)

    cells = d["cells"]
    exps = d["exps"]
    stack = [(r["strike"], r["rowNetWallGex"]) for r in d["rows"]]
    b, cs = boundary(stack, spot)

    # ── ① 真正有信息量的：净 dealer GEX 的符号
    tot = sum(v for _, v in stack)
    print(f"\n■ 净 dealer GEX（{len(exps)} 个到期合计）= {tot/1e6:+.2f}M")
    print("  " + ("正 → 做市商净 long gamma → 对冲高抛低吸 → 倾向压波动、磨"
                  if tot > 0 else
                  "负 → 做市商净 short gamma → 对冲追涨杀跌 → 倾向放波动、走单边"))

    # ── ② 符号分界：本端点上基本没意义，必须带诊断一起报
    print(f"\n■ 符号分界（⚠️ 不是 flip，见下方诊断）")
    if b:
        x, k0, k1, v0, v1 = b
        print(f"  位置 {x:.2f}（{(x-spot)/spot*100:+.2f}% vs 现价）"
              f"　夹住两档 {k0}({v0/1e6:+.2f}M) ↔ {k1}({v1/1e6:+.2f}M)")
    print(f"  翻转点共 {len(cs)} 个"
          + ("　⛔ **>20 个 = 符号结构是碎的，「取最近现价」必然落在现价上，"
             "这个数没有信息量，别当位用**" if len(cs) > 20 else
             "　（<20 个，相对可读，但仍无官方值可对答案）"))
    if b and abs(x-spot)/spot < 0.015:
        print(f"  ⚠️ 它离现价只有 {abs(x-spot)/spot*100:.2f}% —— 这是「贴现价」的典型症状，"
              f"不是结构给出的位")
    print(f"  ⚠️ 厚度指标在本端点上有偏（平值附近 gamma 天然最大，会虚高），不要照搬 flip.py 的阈值")

    # 2) 逐到期列
    print(f"\n■ 逐到期列")
    print(f"  {'到期':<12}{'DTE':>4}{'档数':>5}{'净GEX(M)':>11}{'分界位':>10}{'厚度':>7}  结构")
    for e in exps:
        rows = [(c["strike"], c["netDealerGex"]) for c in cells
                if c["expiration"] == e["date"] and c["netDealerGex"] != 0]
        if len(rows) < 3:
            continue
        net = sum(v for _, v in rows)
        bb, cc = boundary(rows, spot)
        mx = max(abs(v) for _, v in rows) or 1
        if bb:
            th = max(abs(bb[3]), abs(bb[4]))/mx*100
            thr = mx*0.05
            rc = crossings([(k, v) for k, v in rows if abs(v) >= thr])
            robust = "✓" if rc else "假位"
            print(f"  {e['date']:<12}{e['dte']:>4}{len(rows):>5}{net/1e6:>11.2f}"
                  f"{bb[0]:>10.2f}{th:>6.0f}%  {robust}")
        else:
            print(f"  {e['date']:<12}{e['dte']:>4}{len(rows):>5}{net/1e6:>11.2f}"
                  f"{'—':>10}{'—':>7}  单向")

    # ── 官方 Standard GEX flip（若该标的在白名单内，这才是验证过的那个）
    sf = std_flip(t)
    print(f"\n■ 官方 Standard GEX flip（100% 复现验证过的那个）")
    if sf.get("ok"):
        for g, v in sf["g"].items():
            if v.get("flip"):
                print(f"  {g:<8} flip = {v['flip']:.2f}"
                      f"　({(v['flip']-sf['spot'])/sf['spot']*100:+.2f}% vs 现价 {sf['spot']})")
        if b:
            best = next((v["flip"] for v in sf["g"].values() if v.get("flip")), None)
            if best:
                print(f"  ↕ 与上面 Heatmap 符号分界相距 {abs(best-b[0])/spot*100:.2f}% 价格"
                      f" —— 两个口径不是同一条线")
    else:
        print(f"  该标的不在 Standard GEX 白名单内（仅 SPX/SPY/QQQ/IWM/AAPL/MSFT/"
              f"GOOGL/AMZN/NVDA/META/TSLA）→ **没有经验证的 flip 可用**")

    # 3) 现价附近最强的行（吸引子/边界）
    top = sorted(d["rows"], key=lambda r: -abs(r["rowNetWallGex"]))[:8]
    print(f"\n■ 量级最大的行权价（跨全到期合计）")
    print(f"  {'行权价':>8}{'净GEX(M)':>11}{'距现价':>9}  性质")
    for r in top:
        k, v = r["strike"], r["rowNetWallGex"]
        print(f"  {k:>8}{v/1e6:>11.2f}{(k-spot)/spot*100:>8.1f}%  "
              f"{'大正 = 吸引子/减速带' if v > 0 else '大负 = 加速走廊'}")

    if chart:
        print(f"\n■ 现价 ±{near} 档（全到期合计）")
        st = sorted(stack, key=lambda r: r[0])
        idx = min(range(len(st)), key=lambda i: abs(st[i][0]-spot))
        win = st[max(0, idx-near): idx+near+1]
        mx = max(abs(v) for _, v in win) or 1
        prev = None
        for k, v in reversed(win):
            n = max(1, int(abs(v)/mx*16))
            bar = " "*16 + "█"*n if v > 0 else " "*(16-n) + "█"*n
            if prev and prev[1]*v < 0:
                print(f"  {'':>8}{'':>11}  {'─'*34}  ← 分界")
            star = " ◄现价" if abs(k-spot) < 0.75 else ""
            print(f"  {k:>8}{v/1e6:>10.2f}M  {bar}{star}")
            prev = (k, v)


if __name__ == "__main__":
    a = sys.argv[1:]
    chart = "--chart" in a
    ts = [x.upper() for x in a if not x.startswith("--")]
    if not ts:
        print(__doc__); sys.exit(0)
    ensure_page()
    for t in ts:
        report(t, chart)
