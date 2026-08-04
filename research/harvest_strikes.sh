#!/bin/bash
# 采集 per-strike GEX（harvest_api.sh 丢掉的 strikes[]），用于自算 flip / 建仓位
# 用法: harvest_strikes.sh 2026-07-22 [more dates...]
# 输出: strikes/st_DATE.json  —— 每 5 分钟一帧, netGex 单位=千美元
export PATH="$HOME/.npm-global/bin:$PATH"
S=svb6mefm
OUT=${GEXFLIP_DATA:-$HOME/trading-reports/nightwatch_replay_dataset}/strikes
mkdir -p "$OUT"
CUR=$(opencli browser $S state 2>/dev/null | grep -m1 "^URL:" | grep -c yehangshe)
if [ "$CUR" != "1" ]; then
  opencli browser $S open "https://yehangshe.com/app/dashboard" >/dev/null 2>&1; sleep 8
fi
opencli browser $S eval '(async()=>{const r=await fetch("/api/auth/refresh",{method:"POST"});return r.status;})()' >/dev/null 2>&1
for D in "$@"; do
  [ -s "$OUT/st_$D.json" ] && { echo "$D SKIP(已存在)"; continue; }
  timeout 180 opencli browser $S eval "
(async () => {
  try {
    const r = await fetch('/api/replay-lab/day-overlays?ticker=SPX&date=$D&dealerGexSignConvention=dealer-signed-v1').then(x=>x.json());
    if(!r.success) return JSON.stringify({date:'$D', ok:false, err:'overlays'});
    const fr = r.data.standardGexFrames||[];
    const out=[];
    for(let i=0;i<fr.length;i+=5){ const f=fr[i];
      out.push({t:f.snapshotAt, spot:f.spot, flip:f.summary.gammaFlip,
                tg:Math.round(f.summary.totalGex/1e6),
                s:(f.strikes||[]).map(s=>[s.strike, Math.round(s.netGex/1e3), Math.round(s.callGex/1e3)])}); }
    if(fr.length && (fr.length-1)%5!==0){ const f=fr[fr.length-1];
      out.push({t:f.snapshotAt, spot:f.spot, flip:f.summary.gammaFlip,
                tg:Math.round(f.summary.totalGex/1e6),
                s:(f.strikes||[]).map(s=>[s.strike, Math.round(s.netGex/1e3), Math.round(s.callGex/1e3)])}); }
    return JSON.stringify({date:'$D', ok:true, n:out.length, frames:out});
  } catch(e) { return JSON.stringify({date:'$D', ok:false, err:String(e).slice(0,80)}); }
})()" 2>/dev/null > /tmp/st_$D.txt
  python3 - "$D" "$OUT" << 'PYEOF'
import json, sys
D, OUT = sys.argv[1], sys.argv[2]
try:
    raw = open(f'/tmp/st_{D}.txt').read()
    s, e = raw.find('{'), raw.rfind('}')+1
    d = json.loads(raw[s:e])
    if isinstance(d, str): d = json.loads(d)
    if not d.get('ok'):
        print(D, 'FAIL', d.get('err')); sys.exit()
    json.dump(d, open(f'{OUT}/st_{D}.json', 'w'))
    f = d['frames'][-1]
    nofl = sum(1 for x in d['frames'] if x.get('flip') is None)
    print(D, 'OK', f"{d['n']}帧 收盘spot={f['spot']} flip={f.get('flip')} strikes={len(f['s'])} 无flip帧={nofl}")
except Exception as ex:
    print(D, 'ERR', str(ex)[:100])
PYEOF
  rm -f /tmp/st_$D.txt
done
echo "STRIKES HARVEST DONE"
