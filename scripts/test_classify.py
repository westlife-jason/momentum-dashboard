"""
classify.py 단위 테스트 — HANDOFF 스펙 7절의 7개 인수 케이스.
DB 없이 동작한다.  실행: python scripts/test_classify.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from classify import compute_signals, classify  # noqa: E402


def run(name, closes, vols, scores, ticker, lows=None):
    """가격 시계열로 시그널 계산 + 분류. lows 미지정 시 close-1 로 생성."""
    lows = lows if lows is not None else [c - 1 for c in closes]
    sig = compute_signals(closes, lows, vols, scores, ticker)
    return classify(sig), sig


RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, cond, detail))
    print(f"  {'✅' if cond else '❌'} {name}" + (f"  — {detail}" if detail and not cond else ""))


# ── 1. DELL형: close>20MA>50MA, RSI 양호, 거래량 동반, 실적 UP → BUY
closes = [100 + 0.5 * i for i in range(80)]
state, s = run("DELL", closes, [1000] * 79 + [1400], [70, 75], "DELL")
check("1. DELL형 → BUY", state == "BUY", f"got {state} / {s['reasons']}")

# ── 2. MRVL/COHR형: 실적 UP이나 50MA 하단 + 거래량 절반 → WATCH
closes = [100] * 79 + [98.7]
state, s = run("MRVL", closes, [1000] * 79 + [500], [70, 75], "MRVL")
check("2. MRVL형 → WATCH", state == "WATCH", f"got {state}")
check("2. reason '50MA 하단'", any("50MA 하단" in r for r in s["reasons"]), str(s["reasons"]))
check("2. reason '거래량 미확정'", any("거래량 미확정" in r for r in s["reasons"]), str(s["reasons"]))

# ── 3. VRT형: 50MA 확정 이탈 + 20MA<50MA → EXIT_IMMINENT
closes = [100] * 60 + [100 - 1.0 * i for i in range(1, 21)]
state, s = run("VRT", closes, [1000] * 80, [70, 68], "VRT")
check("3. VRT형 → EXIT_IMMINENT", state == "EXIT_IMMINENT", f"got {state}")
check("3. exit_triggered=True", s["exit_triggered"] is True)

# ── 4. 전저점 확정 이탈 → EXIT_IMMINENT, exit_triggered=True
closes = [96] * 70 + [93]
state, s = run("SWING", closes, [1000] * 71, [70, 70], "SWING")
check("4. 전저점 이탈 → EXIT_IMMINENT", state == "EXIT_IMMINENT", f"got {state}")
check("4. exit_triggered=True", s["exit_triggered"] is True)
check("4. reason에 '전저점'", any("전저점" in r for r in s["reasons"]), str(s["reasons"]))

# ── 5. 휩쏘 필터: 장중 저가만 50MA -0.5% 이탈, 종가는 위 → EXIT 아님
closes = [100] * 79 + [100.2]
lows = [99] * 79 + [99.5]          # 마지막 날 장중 저가만 50MA 아래
state, s = run("WHIP", closes, [1000] * 80, [70, 75], "WHIP", lows=lows)
check("5. 휩쏘 → EXIT 아님", state != "EXIT_IMMINENT", f"got {state}")
check("5. exit_triggered=False", s["exit_triggered"] is False)

# ── 6. 청산임박(미이탈): 50MA 위 +1.2%, 데드크로스 → EXIT_IMMINENT, exit_triggered=False
closes = [110] * 30 + [100] * 19 + [107.42]
state, s = run("NEAR", closes, [1000] * 50, [70, 70], "NEAR")
check("6. 청산임박 → EXIT_IMMINENT", state == "EXIT_IMMINENT", f"got {state}")
check("6. exit_triggered=False", s["exit_triggered"] is False, str(s["reasons"]))
check("6. dist 0~2% 이내", s["dist_to_exit_pct"] is not None and 0 <= s["dist_to_exit_pct"] <= 2.0,
      str(s.get("dist_to_exit_pct")))

# ── 7. 사이클 함정: 메모리 종목은 밸류가 BUY로 끌어올리지 못함 + caution=True
closes = [100] * 79 + [98.7]        # 50MA 하단 (2번과 동일 조건)
state, s = run("MU", closes, [1000] * 79 + [500], [70, 75], "MU")
check("7. 사이클 종목이 밸류로 BUY 되지 않음", state != "BUY", f"got {state}")
check("7. valuation_caution=True", s["valuation_caution"] is True)
check("7. reason에 '사이클'", any("사이클" in r for r in s["reasons"]), str(s["reasons"]))

# ── 요약
print()
passed = sum(1 for _, c, _ in RESULTS if c)
total = len(RESULTS)
print(f"결과: {passed}/{total} 통과")
sys.exit(0 if passed == total else 1)
