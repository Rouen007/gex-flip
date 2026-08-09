#!/usr/bin/env python3
"""
从原始期权链自算 GEX 剖面 → 推 flip（用于夜航社未启用的标的，如 INTC / PANW）

管道：Yahoo 期权链(strike / OI / IV) → Black-Scholes gamma → 每档 netGex
      → 套用已验证的三步算法（符号翻转 + 线性插值 + 取最近现价）

🧪 **实验性 —— 精度远不如 flip.py，别当准数用。**
   2026-08-05 校验（--validate）：META 差 0.38% / AAPL 1.59% / TSLA 2.90% / NVDA 4.72% 价格。
   误差来源有两块，都还没拆开：
     ① **到期不匹配** —— 本脚本默认取最近到期（当天 0DTE），夜航社对的是 1dte 组，
        比的不是同一批合约。要公平比必须先对齐到期。
     ② IV / 无风险利率 / gamma 口径与数据商不同，且 Yahoo 的 OI 是**昨收快照**。
   用途：给不在夜航社白名单的标的（INTC/PANW/ORCL）一个**数量级参考**，
   判断"结构大致偏正还是偏负、分界大概在哪一带"，不要报小数点。

用法：
    python3 flip_from_chain.py INTC PANW
    python3 flip_from_chain.py --validate NVDA TSLA AAPL   # 和夜航社官方 flip 对答案
"""
import sys, os, math, json, time
import urllib.request, urllib.parse, urllib.error

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_JAR = urllib.request.HTTPCookieProcessor()
_OP = urllib.request.build_opener(_JAR)
_OP.addheaders = [("User-Agent", UA)]
_CRUMB = None


def _get(url, tries=3):
    for i in range(tries):
        try:
            with _OP.open(url, timeout=20) as r:
                return r.read().decode()
        except Exception as e:
            if i == tries-1:
                raise
            time.sleep(1.5)


def crumb():
    global _CRUMB
    if _CRUMB:
        return _CRUMB
    try:
        _get("https://fc.yahoo.com")
    except Exception:
        pass
    _CRUMB = _get("https://query2.finance.yahoo.com/v1/test/getcrumb").strip()
    return _CRUMB


def chain(sym, expiry_ts=None):
    """拉 Yahoo 期权链。返回 (spot, 到期时间戳列表, 该到期的 calls/puts)"""
    base = f"https://query2.finance.yahoo.com/v7/finance/options/{sym}"
    q = {"crumb": crumb()}
    if expiry_ts:
        q["date"] = str(expiry_ts)
    j = json.loads(_get(base + "?" + urllib.parse.urlencode(q)))
    res = (j.get("optionChain") or {}).get("result") or []
    if not res:
        raise RuntimeError(f"{sym}: 无期权链数据")
    r = res[0]
    spot = (r.get("quote") or {}).get("regularMarketPrice")
    exps = r.get("expirationDates") or []
    opts = (r.get("options") or [{}])[0]
    return spot, exps, opts.get("calls") or [], opts.get("puts") or []


# ══════════ Black-Scholes gamma ══════════
def _npdf(x):
    return math.exp(-x*x/2)/math.sqrt(2*math.pi)


def bs_gamma(S, K, T, iv, r=0.045):
    """标准 BS gamma。T 单位=年，iv 单位=小数"""
    if S <= 0 or K <= 0 or T <= 0 or iv <= 0:
        return 0.0
    d1 = (math.log(S/K) + (r + iv*iv/2)*T) / (iv*math.sqrt(T))
    return _npdf(d1) / (S * iv * math.sqrt(T))


def build_profile(spot, calls, puts, T):
    """→ {strike: netGex}，口径与夜航社一致：call 记正、put 记负
       GEX = gamma × OI × 100 × spot²  × 0.01（每 1% 价格变动的美元 gamma 敞口）"""
    prof, detail = {}, {}
    mult = 100 * spot * spot * 0.01
    for side, rows in (("c", calls), ("p", puts)):
        for o in rows:
            K = o.get("strike")
            oi = o.get("openInterest") or 0
            iv = o.get("impliedVolatility") or 0
            if not K or oi <= 0 or iv <= 0:
                continue
            g = bs_gamma(spot, K, T, iv) * oi * mult
            d = detail.setdefault(K, {"c": 0.0, "p": 0.0, "coi": 0, "poi": 0})
            if side == "c":
                d["c"] += g; d["coi"] += oi
            else:
                d["p"] += g; d["poi"] += oi
    for K, d in detail.items():
        prof[K] = d["c"] - d["p"]
    return prof, detail


# ══════════ 已验证的三步算法 ══════════
def crossings(rows):
    rows = sorted(rows)
    out = []
    for i in range(len(rows)-1):
        (k0, v0), (k1, v1) = rows[i], rows[i+1]
        if v0 == 0 or v1 == 0 or v0*v1 >= 0:
            continue
        out.append((k0 + (k1-k0)*(0-v0)/(v1-v0), k0, k1, v0, v1))
    return out


def flip_of(rows, spot):
    cs = crossings(rows)
    return (min(cs, key=lambda c: abs(c[0]-spot)), cs) if cs else (None, [])


def analyze(sym, exp_idx=0, quiet=False):
    spot, exps, calls, puts = chain(sym)
    if exp_idx and exp_idx < len(exps):
        spot, exps, calls, puts = chain(sym, exps[exp_idx])
    exp_ts = exps[exp_idx] if exp_idx < len(exps) else exps[0]
    T = max((exp_ts - time.time())/(365.25*24*3600), 1/365/24)
    prof, detail = build_profile(spot, calls, puts, T)
    rows = [(k, v) for k, v in prof.items() if v != 0]
    if len(rows) < 3:
        return None
    best, cs = flip_of(rows, spot)
    mx = max(abs(v) for _, v in rows)
    out = dict(sym=sym, spot=spot, T=T,
               exp=time.strftime("%Y-%m-%d", time.localtime(exp_ts)),
               dte=round(T*365.25, 2), nstrike=len(rows), ncross=len(cs),
               flip=best[0] if best else None, mx=mx, rows=rows, detail=detail)
    if best:
        out["k0"], out["k1"] = best[1], best[2]
        out["v0"], out["v1"] = best[3], best[4]
        out["thick"] = max(abs(best[3]), abs(best[4]))/mx*100
        thr = mx*0.05
        rc = crossings([(k, v) for k, v in rows if abs(v) >= thr])
        out["robust"] = min((c[0] for c in rc), key=lambda z: abs(z-spot)) if rc else None
        others = [c[0] for c in cs if abs(c[0]-best[0]) > 1e-9]
        out["jump"] = min((abs(c-best[0]) for c in others), default=None)
    return out


def show(a, chart=False):
    if not a:
        print("  数据不足"); return
    print(f"\n{a['sym']}  现价 {a['spot']:.2f}   到期 {a['exp']} (DTE {a['dte']})"
          f"   有效行权价 {a['nstrike']}  翻转点 {a['ncross']} 个")
    if a["flip"] is None:
        print("  ⚠️ 无符号翻转点 → 该到期结构单向，flip 不存在")
        return
    v = "厚，可信" if a["thick"] >= 20 else "中等" if a["thick"] >= 5 else "薄 ⚠️ 噪音别当位用"
    print(f"  自算 flip = {a['flip']:.2f}   ({(a['flip']-a['spot'])/a['spot']*100:+.2f}% vs 现价)")
    print(f"    夹住两档：{a['k0']} ({a['v0']/1e6:+.1f}M) ↔ {a['k1']} ({a['v1']/1e6:+.1f}M)")
    print(f"    厚度 {a['thick']:.1f}% → {v}")
    if a.get("jump"):
        print(f"    瞬移风险：次近翻转点距 {a['jump']/a['spot']*100:.2f}% 价格")
    if a["robust"] is None:
        print("    ⚠️ 稳健检验：过滤小单后翻转点消失 → 假位，结构其实单向")
    else:
        print(f"    稳健检验：{a['robust']:.2f}"
              f"（差 {abs(a['robust']-a['flip'])/a['spot']*100:.2f}%）")
    print(f"    制度：现价{'在 flip 上方 → 净 long gamma → 高抛低吸压波动'
                        if a['spot'] > a['flip'] else
                        '在 flip 下方 → 净 short gamma → 追涨杀跌放波动'}")
    if chart:
        rows = sorted(a["rows"])
        idx = min(range(len(rows)), key=lambda i: abs(rows[i][0]-a["spot"]))
        win = rows[max(0, idx-9): idx+10]
        mx = max(abs(r[1]) for r in win) or 1
        print(f"    {'行权价':>8} {'netGex':>10}  {'颜色':<8} 条形 负←|→正")
        prev = None
        for k, nv in reversed(win):
            n = max(1, int(abs(nv)/mx*14))
            bar = " "*14 + "█"*n if nv > 0 else " "*(14-n) + "█"*n
            if prev is not None and prev[1]*nv < 0 and min(k, prev[0]) <= a["flip"] <= max(k, prev[0]):
                print(f"    {'':>8} {'':>10}  {'─'*38}  ← FLIP {a['flip']:.2f}")
            st = " ◄现价" if abs(k-a["spot"]) <= (win[1][0]-win[0][0])/2 else ""
            print(f"    {k:>8} {nv/1e6:>9.1f}M  {'橙/黄正' if nv>0 else '深紫负':<8}{bar}{st}")
            prev = (k, nv)


if __name__ == "__main__":
    args = sys.argv[1:]
    val = "--validate" in args
    chart = "--chart" in args
    ts = [x.upper() for x in args if not x.startswith("--")]
    if not ts:
        print(__doc__); sys.exit(0)
    if val:
        print("="*74)
        print("自算管道校验：Yahoo 期权链 + BS gamma  vs  夜航社官方 gammaFlip")
        print("="*74)
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from flip import fetch as yhs_fetch, ensure_page
        ensure_page()
        for t in ts:
            a = analyze(t)
            d = yhs_fetch(t)
            off = None
            if d.get("ok"):
                for g, v in d["g"].items():
                    if v.get("flip"):
                        off = (g, v["flip"], d["spot"]); break
            if a and off:
                err = abs(a["flip"]-off[1])
                print(f"{t:<6} 自算 {a['flip']:8.2f} (DTE {a['dte']:.2f}, 现价 {a['spot']:.2f})  |  "
                      f"夜航社 {off[1]:8.2f} ({off[0]}, 现价 {off[2]:.2f})  |  "
                      f"差 {err:6.2f} = {err/a['spot']*100:.2f}% 价格")
            else:
                print(f"{t:<6} 自算 {a['flip'] if a else None} / 夜航社 {off}")
    else:
        for t in ts:
            try:
                show(analyze(t), chart)
            except Exception as e:
                print(f"\n{t}: 失败 —— {e}")
