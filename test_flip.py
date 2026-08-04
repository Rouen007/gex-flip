#!/usr/bin/env python3
"""自检：不联网、不需要数据集，clone 下来直接能跑。

用真实盘面快照当固定用例，验证 flip 算法与数据商官方 gammaFlip 一致。
    python3 test_flip.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flip import flip_of, crossings, quality, verdict

FAIL = 0


def check(name, got, want, tol=0.005):
    global FAIL
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: 自算 {got if got is None else f'{got:.4f}'} "
          f"/ 官方 {want}")
    if not ok:
        FAIL += 1


# ── 用例 1: TSLA 1dte @ 2026-08-04 23:35 ET（现价 323.45，官方 gammaFlip 315.5443…）
#    夹住 flip 的两档 315 = -83.8M、317.5 = +300.6M
TSLA_1DTE = [(297.5, -5.6e6), (300, 99.6e6), (302.5, -8.4e6), (305, -126.2e6),
             (307.5, -7.1e6), (310, -10.8e6), (312.5, -77.2e6), (315, -83.8e6),
             (317.5, 300.6e6), (320, 248.2e6), (322.5, 1103.7e6), (325, 1367.7e6),
             (327.5, 361.1e6), (330, 1544.1e6), (332.5, 347.0e6), (335, 474.9e6)]

# ── 用例 2: NVDA 1dte @ 2026-08-04 23:40 ET（现价 210.35，官方 gammaFlip 202.6050…）
NVDA_1DTE = [(185, -22.2e6), (187.5, -58.0e6), (190, -32.1e6), (192.5, -9.2e6),
             (195, -165.6e6), (197.5, -176.3e6), (200, -145.8e6), (202.5, -19.4e6),
             (205, 442.1e6), (207.5, 1844.5e6), (210, 4009.3e6), (212.5, 3144.9e6),
             (215, 3387.0e6), (217.5, 760.1e6), (220, 939.8e6)]

# ── 用例 3: SPX 2026-07-22 09:30 首帧（现价 7496.88，官方 gammaFlip 7495.0387）
#    这帧有 10 个翻转点，是「取离现价最近」这条规则的关键用例：
#    7490→7495 的上穿在 7494.98，7495→7500 的下穿在 7495.04，官方取了后者（离现价更近）
SPX_FRAME0 = [(7480, -45980e6), (7485, 750e6), (7490, -13234e6), (7495, 66e6),
              (7500, -8438e6), (7505, -1543e6), (7510, 29326e6), (7515, 39640e6),
              (7520, 68157e6), (7525, 91894e6)]

print("=" * 66)
print("gex-flip 自检 —— 算法 vs 数据商官方 gammaFlip")
print("=" * 66)

print("\n[1] 基本复现")
for nm, rows, spot, want in [
        ("TSLA 1dte", TSLA_1DTE, 323.45, 315.5443),
        ("NVDA 1dte", NVDA_1DTE, 210.35, 202.6050),
        ("SPX  09:30", SPX_FRAME0, 7496.88, 7495.0387)]:
    best, _ = flip_of(rows, spot)
    check(nm, best[0] if best else None, want)

print("\n[2] 「取离现价最近」这条规则不能省")
best, cs = flip_of(SPX_FRAME0, 7496.88)
xs = sorted(c[0] for c in cs)
print(f"  这一帧共 {len(cs)} 个翻转点: {[round(x, 2) for x in xs]}")
print(f"  取最低  → {xs[0]:.2f}   (错，差 {abs(xs[0]-7495.0387):.2f})")
print(f"  取最高  → {xs[-1]:.2f}   (错，差 {abs(xs[-1]-7495.0387):.2f})")
print(f"  取最近现价 → {best[0]:.4f}   (对)")
if abs(xs[0] - 7495.0387) < 0.005:
    print("  ⚠️ 这个用例区分不出规则，换一帧"); FAIL += 1

print("\n[3] ⛔ 累加和(cumsum)穿零口径是错的")
run, cum = 0.0, []
for k, v in sorted(SPX_FRAME0):
    run += v; cum.append((k, run))
zs = [c[0] for c in crossings(cum)]
print(f"  累加和穿零 → {[round(z, 2) for z in zs] or '无零点'}"
      f"   官方 7495.04 → {'完全没算出来' if not zs else f'最近的差 {min(abs(z-7495.0387) for z in zs):.2f} 点'}")

print("\n[4] 质量评分（个股防坑）")
best, _ = flip_of(NVDA_1DTE, 210.35)
q = quality(NVDA_1DTE, best, 210.35)
print(f"  NVDA 厚度 {q['thick']:.1f}% → {verdict(q)}")
print(f"  NVDA 一档 {q['step']} = 现价的 {q['step_pct']:.2f}%（分辨率上限）")
rob = "翻转点消失，原 flip 是假位 ✓预期如此" if q["robust"] is None else f"{q['robust']:.2f}"
print(f"  NVDA 稳健重算(只留≥最大节点5%的档) → {rob}")
if q["robust"] is not None:
    print("  ⚠️ 预期 NVDA 过滤后翻转点应消失"); FAIL += 1

print("\n[5] 边界情况")
for nm, rows, spot in [("全正（无 flip）", [(100, 5e6), (105, 8e6), (110, 3e6)], 105),
                       ("全负（无 flip）", [(100, -5e6), (105, -8e6)], 102),
                       ("含 0 值档", [(100, -5e6), (105, 0), (110, 8e6)], 105),
                       ("只有一档", [(100, 5e6)], 100)]:
    best, cs = flip_of(rows, spot)
    print(f"  {'PASS' if best is None else 'FAIL'}  {nm}: 返回 {best[0] if best else None}")
    if best is not None:
        FAIL += 1

print("\n" + "=" * 66)
print(f"{'全部通过 ✓' if FAIL == 0 else f'{FAIL} 项失败 ✗'}")
sys.exit(1 if FAIL else 0)
