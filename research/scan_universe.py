#!/usr/bin/env python3
"""跨标的批量验证：自算 flip vs 官方 gammaFlip，并量化个股特有风险
   （档距分辨率 / flip 瞬移距离）。README 里那两张表就是这个脚本跑出来的。"""
import json, subprocess, sys, os

BR = os.path.expanduser("~/.npm-global/bin/opencli")
SESSION = os.environ.get("YHS_SESSION", "svb6mefm")
TICKERS = ["TSLA", "NVDA", "AAPL", "MSFT", "GOOGL", "AMZN", "META", "AVGO",
           "MU", "SNDK", "SPY", "QQQ", "IWM"]


def flip_from(rows, spot):
    rows = sorted(rows)
    ks = [r[0] for r in rows]; vs = [r[1] for r in rows]
    cross = []
    for i in range(len(ks)-1):
        y0, y1 = vs[i], vs[i+1]
        if y0 == 0 or y1 == 0 or y0*y1 >= 0: continue
        cross.append(ks[i] + (ks[i+1]-ks[i])*(0-y0)/(y1-y0))
    if not cross: return None, []
    return min(cross, key=lambda x: abs(x-spot)), sorted(cross)


def fetch_many(tickers):
    tl = json.dumps(tickers)
    js = f'''(async()=>{{
      await fetch("/api/auth/refresh",{{method:"POST"}});
      const res={{}};
      for(const t of {tl}){{
        try{{
          const j=await fetch(`/api/gex/intraday-history?ticker=${{t}}&expiryGroup=1dte&bucket=5m&session=today&profile=standardGexOverlay`).then(r=>r.json());
          if(!j.success){{res[t]={{ok:false}};continue;}}
          const p=j.data.latestPayload; const g={{}};
          for(const[k,v]of Object.entries(p.expiryGroups||{{}}))
            g[k]={{flip:(v.summary||{{}}).gammaFlip,
                  s:(v.strikes||[]).filter(x=>x.netGex!==0).map(x=>[x.strike,x.netGex])}};
          res[t]={{ok:true,spot:p.spot,stale:p.isStale,g:g}};
        }}catch(e){{res[t]={{ok:false,err:String(e).slice(0,50)}};}}
      }}
      return JSON.stringify(res);
    }})()'''
    r = subprocess.run([BR, "browser", SESSION, "eval", js],
                       capture_output=True, text=True, timeout=400)
    s, e = r.stdout.find('{'), r.stdout.rfind('}')+1
    d = json.loads(r.stdout[s:e])
    return json.loads(d) if isinstance(d, str) else d


def main():
    data = fetch_many(TICKERS)
    print("="*100)
    print("个股 flip 算法验证（自算 vs 官方 gammaFlip）+ 分辨率/瞬移风险")
    print("="*100)
    print(f"{'标的':<7}{'现价':>9}{'到期':<8}{'自算flip':>10}{'官方flip':>10}{'偏差':>8}"
          f"{'档距%':>7}{'翻转点':>6}{'flip距现价%':>11}{'次近翻转点跳幅%':>15}")
    ok = bad = 0
    for t in TICKERS:
        d = data.get(t) or {}
        if not d.get("ok"):
            print(f"{t:<7}  取数失败"); continue
        spot = d["spot"]
        for gname, gv in d["g"].items():
            rows = [(r[0], r[1]) for r in gv["s"]]
            if len(rows) < 3: continue
            f, cross = flip_from(rows, spot)
            off = gv.get("flip")
            if f is None or off is None: continue
            err = abs(f-off)
            ok += (err < 0.001); bad += (err >= 0.001)
            ks = sorted(r[0] for r in rows)
            diffs = sorted(ks[i+1]-ks[i] for i in range(len(ks)-1))
            step = diffs[len(diffs)//2]
            # flip 瞬移风险：现价往哪边走会切到下一个翻转点
            others = [c for c in cross if abs(c-f) > 1e-6]
            jump = min((abs(c-f) for c in others), default=float('nan'))
            print(f"{t:<7}{spot:>9.2f}{gname:<8}{f:>10.3f}{off:>10.3f}{err:>8.4f}"
                  f"{step/spot*100:>7.2f}{len(cross):>6}{(f-spot)/spot*100:>10.2f}%"
                  f"{jump/spot*100:>14.2f}%")
    print(f"\n精确复现 {ok} 组 / 偏差 {bad} 组")


if __name__ == "__main__":
    main()
