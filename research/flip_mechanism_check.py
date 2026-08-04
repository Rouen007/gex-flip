#!/usr/bin/env python3
"""验证 flip 的机制解释：flip 是不是「put 持仓主导 → call 持仓主导」的分界？"""
import json, subprocess, os, sys

BR = os.path.expanduser("~/.npm-global/bin/opencli")
SESSION = "svb6mefm"


def fetch(t, group="1dte"):
    js = f'''(async()=>{{
      await fetch("/api/auth/refresh",{{method:"POST"}});
      const j=await fetch("/api/gex/intraday-history?ticker={t}&expiryGroup={group}&bucket=5m&session=today&profile=standardGexOverlay").then(r=>r.json());
      if(!j.success) return JSON.stringify({{ok:false}});
      const p=j.data.latestPayload; const g={{}};
      for(const[k,v]of Object.entries(p.expiryGroups||{{}}))
        g[k]={{flip:(v.summary||{{}}).gammaFlip,
              s:(v.strikes||[]).map(x=>[x.strike,x.netGex,x.callGex,x.putGex,x.callOi,x.putOi])}};
      return JSON.stringify({{ok:true,spot:p.spot,g:g}});
    }})()'''
    r = subprocess.run([BR, "browser", SESSION, "eval", js], capture_output=True, text=True, timeout=200)
    s, e = r.stdout.find('{'), r.stdout.rfind('}')+1
    if s < 0: return None
    d = json.loads(r.stdout[s:e])
    return json.loads(d) if isinstance(d, str) else d


for t in (sys.argv[1:] or ["TSLA", "NVDA", "AAPL"]):
    d = fetch(t.upper())
    if not d or not d.get("ok"):
        print(f"{t}: 取数失败"); continue
    spot = d["spot"]
    print("="*80)
    print(f"{t.upper()}  现价 {spot}")
    for g, v in d["g"].items():
        f = v.get("flip")
        rows = [r for r in v["s"] if r[1] != 0]
        if not f or not rows: continue
        # 1) 检查符号约定
        neg_call = sum(1 for r in rows if r[2] < 0)
        pos_put = sum(1 for r in rows if r[3] > 0)
        # 2) flip 上下 put/call 主导
        below = [r for r in rows if r[0] < f]
        above = [r for r in rows if r[0] > f]
        def dom(rs):
            c = sum(r[2] for r in rs); p = abs(sum(r[3] for r in rs))
            return c, p, ("call主导" if c > p else "put主导")
        cb, pb, db = dom(below); ca, pa, da = dom(above)
        # 3) OI 口径同样检查
        def oid(rs):
            co = sum(r[4] for r in rs); po = sum(r[5] for r in rs)
            return co, po, ("callOI多" if co > po else "putOI多")
        cob, pob, ob = oid(below); coa, poa, oa = oid(above)
        print(f"\n 【{g}】flip={f:.2f}   符号约定检查: callGex<0 的档 {neg_call} 个, putGex>0 的档 {pos_put} 个 "
              f"（都应为 0 → call记正/put记负）")
        print(f"   flip 下方: callGEX {cb/1e9:8.2f}B  |putGEX| {pb/1e9:8.2f}B  → {db}"
              f"   ｜ callOI {cob:>7} putOI {pob:>7} → {ob}")
        print(f"   flip 上方: callGEX {ca/1e9:8.2f}B  |putGEX| {pa/1e9:8.2f}B  → {da}"
              f"   ｜ callOI {coa:>7} putOI {poa:>7} → {oa}")
