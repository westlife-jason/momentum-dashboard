"""
모멘텀 대시보드 - 3상태 분류 레이어 (BUY / WATCH / EXIT_IMMINENT)
HANDOFF_momentum_classifier.md 스펙 구현.

- 기존 3조건 점수는 그대로 두고, 그 위에 티커별 상태를 분류해 저장한다.
- 분류는 '종목(ticker) 기준' → momentum_classification 테이블 (owner 무관, 중복 티커 1회만 계산)
- 가격/점수 갱신 이후 실행. 전 종목을 매번 계산하므로 이 스크립트 자체가 백필이다.
- 매매 자동화가 아니라 의사결정 보조 플래그.

시크릿: SUPABASE_URL, SUPABASE_ANON_KEY
수동 실행: python scripts/classify.py
"""
import os
import json
from datetime import date

import requests

# 단위 테스트가 DB 없이 import 할 수 있도록 지연 로드(.get 사용)
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_ANON_KEY", "")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# ================================================================
# 설정값 — 전부 튜너블 (후속 백테스트를 위해 한 곳에 모음)
# ================================================================
CONFIG = {
    "rsi_healthy_min":        50,    # 이 미만이면 주가 모멘텀 약함
    "rsi_overbought":         70,    # 초과 시 BUY 유지하되 chase 경고
    "volume_confirm_ratio":   1.0,   # 최근 거래량 / 거래량 SMA20
    "break_buffer_pct":       1.5,   # 종가가 레벨보다 이 % 이상 아래여야 '이탈' (휩쏘 필터)
    "break_confirm_days":     2,     # 또는 이 일수 연속 종가 이탈 시 인정
    "swing_low_lookback":     60,    # 전저점 탐색 구간 (거래일)
    "swing_low_exclude":      5,     # 최근 N일은 전저점 탐색에서 제외
    "proximity_band_pct":     2.0,   # 청산선 위 이 % 이내 + 모멘텀 약화 = 청산임박
    "valuation_headroom_min": 10,    # 적정가 대비 상승여력 최소 % (비-사이클 종목)
    "earnings_flat_band":     0,     # 점수 변화 절대값이 이 이하면 FLAT
    "price_fetch_rows":       120,   # 계산에 필요한 최근 거래일 수
    # v3.6 가격 레벨(ATR)
    "atr_period":             14,    # ATR 기간
    "atr_stop_mult":          1.8,   # 손절 = 현재가 - ATR × 이 배수
    "target_rr":              2.0,   # 저항선 없을 때 목표가 손익비 (현재가 + 리스크 × 이 배수)
    # v3.6 상대강도(RS)
    "rs_lookback":            60,    # 상대강도 비교 기간(거래일)
    "rs_strong_pp":           5.0,   # 벤치 대비 초과수익 이상이면 '강세'
    "rs_weak_pp":            -5.0,   # 이하면 '약세'
    "rs_trend_shift":         20,    # RS 추이: 며칠 전 RS와 비교(≈1개월)
    "rs_trend_band":          2.0,   # |변화폭| 이 이하면 '유지'
    # v3.8 추세 구조 + 매물대
    "struct_lookback":        90,    # 추세구조/되돌림 관찰 구간(거래일)
    "struct_band_pct":        1.0,   # 고점·저점 비교 시 이 % 이내면 '유지'로 간주
    "swing_pivot_k":          5,     # 스윙 피벗: 좌우 이 봉수 내 최고/최저면 피벗으로 인정
    "vp_lookback":            90,    # 매물대 관찰 구간
    "vp_bins":                24,    # 매물대 가격 구간 수
    "vp_node_mult":           1.4,   # 평균 대비 이 배수 이상 거래량이면 '매물벽'
}

# 시장 지수도 분류에 태워 되돌림/저점구조를 계산(대시보드 시장 패널이 읽음)
MARKET_INDICES = ["KS11", "KQ11"]   # KOSPI, KOSDAQ

# 상대강도 벤치마크 매핑 (US 반도체→SOXX, US 기타→SPY, KR→시장지수)
BENCHMARK_MAP = {
    "AMD": "SOXX", "MU": "SOXX", "SNDK": "SOXX", "CRDO": "SOXX", "WDC": "SOXX",
    "TSLA": "SPY", "UNH": "SPY", "TLN": "SPY",
    "005930": "KS11", "000660": "KS11", "001440": "KS11", "403870": "KQ11",
}

def benchmark_for(ticker):
    if ticker in ("KS11", "KQ11"):
        return ticker          # 지수는 자기 자신 → RS=0 (패널에선 RS 미표시)
    if ticker in BENCHMARK_MAP:
        return BENCHMARK_MAP[ticker]
    return "KS11" if (ticker.isdigit() and len(ticker) == 6) else "SPY"

# 사이클(메모리/반도체) 종목 — 밸류로 BUY를 정당화하지 않는다
CYCLICAL = {"000660", "005930", "MU", "SNDK", "WDC", "403870"}

# 티커별 수동 지지선(있으면 swing_low보다 우선). 없으면 비워둔다.
MANUAL_SUPPORT = {}


# ================================================================
# 계산 유틸 (index.html sma()/rsi14() 이식 — 동일 결과)
# ================================================================
def sma(values, n):
    if values is None or len(values) < n:
        return None
    return sum(values[-n:]) / n


def rsi14(closes):
    """index.html rsi14() 와 동일한 계산."""
    if len(closes) < 15:
        return None
    gain = loss = 0.0
    for i in range(len(closes) - 14, len(closes)):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gain += d
        else:
            loss -= d
    if loss == 0:
        return 100.0
    rs = (gain / 14) / (loss / 14)
    return 100 - 100 / (1 + rs)


def confirmed_break(closes, level):
    """휩쏘 필터: 버퍼 이상 하회 OR N일 연속 종가 하회."""
    if level is None or not closes:
        return False
    if closes[-1] < level * (1 - CONFIG["break_buffer_pct"] / 100):
        return True
    n = CONFIG["break_confirm_days"]
    if len(closes) >= n and all(c < level for c in closes[-n:]):
        return True
    return False


def swing_low_of(lows):
    """최근 lookback 구간에서 최근 exclude일을 뺀 구간의 최저 저가."""
    look, excl = CONFIG["swing_low_lookback"], CONFIG["swing_low_exclude"]
    window = lows[-look:] if len(lows) >= look else lows[:]
    if excl > 0:
        window = window[:-excl] if len(window) > excl else []
    return min(window) if window else None


def swing_high_of(highs):
    """최근 lookback 구간에서 최근 exclude일을 뺀 구간의 최고 고가 (저항선)."""
    look, excl = CONFIG["swing_low_lookback"], CONFIG["swing_low_exclude"]
    window = highs[-look:] if len(highs) >= look else highs[:]
    if excl > 0:
        window = window[:-excl] if len(window) > excl else []
    return max(window) if window else None


def atr(highs, lows, closes, period=None):
    """ATR(기간) — True Range의 단순이동평균. 데이터 부족 시 None."""
    period = period or CONFIG["atr_period"]
    n = min(len(highs), len(lows), len(closes))
    if n < period + 1:
        return None
    trs = []
    for i in range(n - period, n):
        tr = max(highs[i] - lows[i],
                 abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    return sum(trs) / len(trs) if trs else None


def price_levels(current, atr_val, support, resistance):
    """진입=현재가 기준 손절/목표/손익비 산출.
    손절: ATR 기반, 지지선이 가까우면 그 살짝 아래로(더 타이트).
    목표: 실제 저항선(현재가 위) — 없으면 리스크×배수 폴백. → R:R이 종목마다 달라짐."""
    out = {"stop_loss": None, "target_price": None, "rr_ratio": None, "target_basis": None}
    if current is None or atr_val is None or atr_val <= 0:
        return out
    stop = current - atr_val * CONFIG["atr_stop_mult"]
    if support is not None and support < current:
        stop = max(stop, support * 0.99)      # 지지선 살짝 아래
    stop = min(stop, current * 0.999)         # 항상 현재가 아래
    risk = current - stop
    if risk <= 0:
        return out
    if resistance is not None and resistance > current * 1.005:
        target = resistance                    # 실제 저항선을 목표로
        basis = "저항선"
    else:
        target = current + risk * CONFIG["target_rr"]   # 신고가 부근 등 저항 없음 → R배수
        basis = f"저항없음(R×{CONFIG['target_rr']})"
    out.update(stop_loss=stop, target_price=target,
               rr_ratio=(target - current) / risk, target_basis=basis)
    return out


def rs_at(stock_closes, bench_closes, offset=0):
    """offset 거래일 전 시점의 상대강도(%p). offset=0 이면 현재."""
    lb = CONFIG["rs_lookback"]
    need = lb + offset + 1
    if len(stock_closes) < need or len(bench_closes) < need:
        return None
    i = -1 - offset
    s_ret = stock_closes[i] / stock_closes[i - lb] - 1
    b_ret = bench_closes[i] / bench_closes[i - lb] - 1
    return (s_ret - b_ret) * 100


def relative_strength(stock_closes, bench_closes):
    """벤치마크 대비 초과수익(%p) — 같은 시장이라 위치 정렬로 근사."""
    return rs_at(stock_closes, bench_closes, 0)


def rs_trend_of(stock_closes, bench_closes):
    """현재 RS − shift거래일 전 RS = 추이(%p). (변화폭, 라벨) 반환."""
    now = rs_at(stock_closes, bench_closes, 0)
    prev = rs_at(stock_closes, bench_closes, CONFIG["rs_trend_shift"])
    if now is None or prev is None:
        return None, None
    trend = now - prev
    band = CONFIG["rs_trend_band"]
    label = "개선" if trend > band else ("악화" if trend < -band else "유지")
    return trend, label


def rs_label_of(rs):
    if rs is None:
        return None
    if rs >= CONFIG["rs_strong_pp"]:
        return "강세"
    if rs <= CONFIG["rs_weak_pp"]:
        return "약세"
    return "중립"


def retracement_frame(highs, lows, close):
    """되돌림: 최근 고점 → 그 이후 저점 하락의 몇 %를 회복했나.
    반환 (peak, trough, retrace_pct). 데이터 부족/무의미 시 (None,None,None)."""
    look = CONFIG["struct_lookback"]
    h = highs[-look:] if len(highs) >= look else highs[:]
    l = lows[-look:] if len(lows) >= look else lows[:]
    if len(h) < 10 or close is None:
        return None, None, None
    pk_i = max(range(len(h)), key=lambda i: h[i])
    peak = h[pk_i]
    after = l[pk_i:]                      # 고점 이후 구간
    if not after:
        return None, None, None
    trough = min(after)
    if peak <= trough:
        return None, None, None
    retr = (close - trough) / (peak - trough) * 100
    return peak, trough, retr


def _swing_points(vals, k, want_high):
    """스윙 피벗: 좌우 k봉 내 최고(고점)/최저(저점)인 지점. 인접 중복은 더 극단값만 유지.
    반환 [(index, value), ...] (시간순)."""
    pts = []
    for i in range(k, len(vals) - k):
        w = vals[i - k:i + k + 1]
        is_piv = (vals[i] >= max(w)) if want_high else (vals[i] <= min(w))
        if not is_piv:
            continue
        if pts and i - pts[-1][0] <= k:   # 직전 피벗과 너무 붙으면 더 극단값만
            more = vals[i] > pts[-1][1] if want_high else vals[i] < pts[-1][1]
            if more:
                pts[-1] = (i, vals[i])
        else:
            pts.append((i, vals[i]))
    return pts


def _lin_trend(pts, band_pct):
    """피벗들의 회귀 추세: 최소제곱 회귀선의 첫→끝 변화율(%)로
    상승(+1)/하락(-1)/유지(0). 최근 한 번의 눌림에 흔들리지 않게 전체를 본다."""
    n = len(pts)
    if n < 2:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0 or my == 0:
        return 0
    slope = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / denom
    change_pct = slope * (xs[-1] - xs[0]) / my * 100   # 회귀선 전체 변화율(%)
    if change_pct > band_pct:
        return 1
    if change_pct < -band_pct:
        return -1
    return 0


def trend_structure(highs, lows):
    """다우이론식 구조 — 관찰구간 '전체' 스윙 고점/저점의 회귀 추세로 판정.
      상승구조 = 고점 추세↑ & 저점 추세↑  | 하락구조 = 고점↓ & 저점↓
      수렴     = 저점↑ & 고점↓            | 그 외(한쪽 유지·확산) = 횡보
    최근 두 스윙만 보던 방식(눌림에 오판)을 회귀 추세로 바꿔 큰 추세를 잡는다.
    피벗이 부족하면 반-분할 최고/최저로 폴백."""
    look = CONFIG["struct_lookback"]
    h = highs[-look:] if len(highs) >= look else highs[:]
    l = lows[-look:] if len(lows) >= look else lows[:]
    if len(l) < 20 or len(h) < 20:
        return None
    k = CONFIG["swing_pivot_k"]
    band = CONFIG["struct_band_pct"]
    hi, lo = _swing_points(h, k, True), _swing_points(l, k, False)
    if len(hi) < 2 or len(lo) < 2:        # 피벗 부족 → 반 분할 2점으로 폴백
        mid = len(l) // 2
        hi = [(0, max(h[:mid])), (len(h) - 1, max(h[mid:]))]
        lo = [(0, min(l[:mid])), (len(l) - 1, min(l[mid:]))]
    th = _lin_trend(hi, band)             # 고점 추세
    tl = _lin_trend(lo, band)             # 저점 추세
    if th > 0 and tl > 0:
        return "상승구조"
    if th < 0 and tl < 0:
        return "하락구조"
    if tl > 0 and th < 0:
        return "수렴"
    return "횡보"


def volume_profile(highs, lows, closes, volumes, close):
    """매물대: 종가를 가격 구간으로 나눠 거래량 밀집대를 찾는다.
    반환 dict(poc, resistance, support). 데이터 부족 시 값들 None."""
    out = {"poc": None, "resistance": None, "support": None}
    look = CONFIG["vp_lookback"]
    c = closes[-look:] if len(closes) >= look else closes[:]
    v = volumes[-look:] if len(volumes) >= look else volumes[:]
    n = min(len(c), len(v))
    if n < 20 or close is None:
        return out
    c, v = c[-n:], v[-n:]
    lo, hi = min(c), max(c)
    if hi <= lo:
        return out
    bins = CONFIG["vp_bins"]
    width = (hi - lo) / bins
    vol = [0.0] * bins
    for price, volu in zip(c, v):
        bi = min(bins - 1, int((price - lo) / width))
        vol[bi] += volu
    centers = [lo + (i + 0.5) * width for i in range(bins)]
    out["poc"] = centers[max(range(bins), key=lambda i: vol[i])]
    avg = sum(vol) / bins
    thresh = avg * CONFIG["vp_node_mult"]
    nodes = [centers[i] for i in range(bins) if vol[i] >= thresh]
    above = [p for p in nodes if p > close * 1.005]
    below = [p for p in nodes if p < close * 0.995]
    out["resistance"] = min(above) if above else None   # 현재가 위 최근접 매물벽
    out["support"] = max(below) if below else None      # 현재가 아래 최근접 매물벽
    return out


def earnings_momentum_from(scores):
    """진단점수 이력의 최근 변화 부호로 대체 (컨센서스 수정 데이터 없음).
    scores: 오래된→최신 순 점수 리스트. 반환: (모멘텀, 근거문자열)"""
    if not scores or len(scores) < 2:
        return "FLAT", "실적 모멘텀: 점수 이력 부족(FLAT 처리)"
    delta = scores[-1] - scores[-2]
    band = CONFIG["earnings_flat_band"]
    if delta > band:
        return "UP", f"실적 UP (진단점수 {delta:+g})"
    if delta < -band:
        return "DOWN", f"실적 DOWN (진단점수 {delta:+g})"
    return "FLAT", "실적 FLAT (진단점수 변화 없음)"


# ================================================================
# 시그널 계산 + 분류 (스펙 2절)
# ================================================================
def compute_signals(closes, lows, volumes, scores, ticker, highs=None, bench_closes=None):
    """분류에 필요한 모든 시그널을 계산. 값이 없으면 None으로 두고 지어내지 않는다.
    highs/bench_closes 는 v3.6(가격레벨/RS)용 — 없으면 해당 항목만 None."""
    s = {"reasons": []}
    close = closes[-1] if closes else None
    s["close"] = close

    ma20, ma50 = sma(closes, 20), sma(closes, 50)
    rsi = rsi14(closes)
    s["sma20"], s["sma50"], s["rsi"] = ma20, ma50, rsi

    # --- 주가 모멘텀 ---
    if None in (close, ma20, ma50, rsi):
        s["price_ok"] = False
        s["reasons"].append("주가 데이터 부족(가격 게이트 미통과)")
    else:
        above_50 = close > ma50
        above_20 = close > ma20
        aligned = ma20 > ma50
        rsi_ok = rsi >= CONFIG["rsi_healthy_min"]
        s["price_ok"] = above_50 and above_20 and aligned and rsi_ok
        if not above_50:
            s["reasons"].append("50MA 하단")
        if not above_20:
            s["reasons"].append("20MA 하단")
        if not aligned:
            s["reasons"].append("20MA < 50MA (단기 구조 이상)")
        if not rsi_ok:
            s["reasons"].append(f"RSI {rsi:.0f} (< {CONFIG['rsi_healthy_min']})")
        if rsi_ok and rsi > CONFIG["rsi_overbought"]:
            s["reasons"].append(f"RSI {rsi:.0f} 과열 — 추격매수 주의")

    # --- 거래량 확인 게이트 ---
    vol_sma20 = sma(volumes, 20)
    cur_vol = volumes[-1] if volumes else None
    if cur_vol is None or not vol_sma20:
        s["volume_confirmed"] = None
        s["reasons"].append("거래량 데이터 없음(게이트 통과 처리)")
    else:
        ratio = cur_vol / vol_sma20
        s["volume_ratio"] = ratio
        s["volume_confirmed"] = ratio >= CONFIG["volume_confirm_ratio"]
        if not s["volume_confirmed"]:
            s["reasons"].append(f"거래량 미확정({ratio:.1f}×)")

    # --- 실적 모멘텀 ---
    s["earnings_momentum"], em_reason = earnings_momentum_from(scores)
    s["reasons"].append(em_reason)

    # --- 청산 시그널 ---
    support = MANUAL_SUPPORT.get(ticker) or swing_low_of(lows)
    s["support_level"] = support
    broke_50 = confirmed_break(closes, ma50)
    broke_sup = confirmed_break(closes, support)
    death_cross = (ma20 < ma50) if (ma20 is not None and ma50 is not None) else False
    s["death_cross"] = death_cross
    s["exit_triggered"] = bool(broke_50 or broke_sup)
    if broke_50:
        s["reasons"].append(f"50MA 확정 이탈({(close/ma50-1)*100:+.1f}%)")
    if broke_sup:
        s["reasons"].append(f"전저점 {support:.2f} 확정 이탈({(close/support-1)*100:+.1f}%)")

    # 청산선까지 거리 (close 아래에 있는 레벨 중 가장 높은 값)
    below = [lv for lv in (ma50, support) if lv is not None and lv <= close] if close else []
    nearest = max(below) if below else None
    if nearest:
        dist = (close - nearest) / nearest * 100
        s["dist_to_exit_pct"] = dist
        s["near_exit"] = (0 <= dist <= CONFIG["proximity_band_pct"]) and \
                         ((rsi is not None and rsi < CONFIG["rsi_healthy_min"]) or death_cross)
        if s["near_exit"]:
            bits = []
            if rsi is not None:
                bits.append(f"RSI {rsi:.0f}")
            if death_cross:
                bits.append("데드크로스")
            s["reasons"].append(f"청산선 {nearest:.2f} 근접(+{dist:.1f}%), " + " + ".join(bits))
    else:
        s["dist_to_exit_pct"] = None
        s["near_exit"] = False

    # --- 밸류에이션 게이트 ---
    # forward EPS/멀티플 근거가 저장소에 없음 → 스펙 3절 폴백: 통과 처리 + reason 명시
    s["valuation_caution"] = ticker in CYCLICAL
    s["valuation_ok"] = True
    if s["valuation_caution"]:
        s["reasons"].append("사이클 종목 — 밸류로 매수 정당화 안 함(낮은 P/E는 함정 가능)")
    else:
        s["reasons"].append("valuation 데이터 없음(게이트 통과 처리)")

    # --- 추세 구조 + 매물대 (v3.8) ---
    if highs:
        peak, trough, retr = retracement_frame(highs, lows, close)
        s["swing_peak"], s["swing_trough"], s["retrace_pct"] = peak, trough, retr
        s["trend_structure"] = trend_structure(highs, lows)
        vp = volume_profile(highs, lows, closes, volumes, close)
        s["vp_poc"], s["vp_resistance"], s["vp_support"] = vp["poc"], vp["resistance"], vp["support"]
        if retr is not None:
            s["reasons"].append(f"되돌림 {retr:.0f}% · {s['trend_structure'] or ''}")
        if vp["resistance"] is not None:
            s["reasons"].append(f"매물벽 저항 {vp['resistance']:.2f}")

    # --- 가격 레벨 (ATR 기반 손절/목표/손익비) v3.6 ---
    atr_val = atr(highs, lows, closes) if highs else None
    # 목표=전고점(진짜 목표, R:R 의미 유지). 매물벽(vp_resistance)은 '1차 저항' 정보로 별도 표시.
    resistance = swing_high_of(highs) if highs else None
    s["atr"] = atr_val
    s["resistance_level"] = resistance
    lv = price_levels(close, atr_val, s.get("support_level"), resistance)
    if s.get("exit_triggered"):
        # 이미 이탈한 종목의 '목표=전고점'은 R:R을 비현실적으로 높여 오해를 부름 → 손절만 유지
        lv["target_price"] = None
        lv["rr_ratio"] = None
        lv["target_basis"] = "이탈 상태(목표 비적용)"
    s.update(lv)
    if s.get("stop_loss") is not None:
        if lv["rr_ratio"] is not None:
            rr = lv["rr_ratio"]
            tag = "손익비 양호" if rr >= 2 else ("손익비 애매" if rr >= 1 else "손익비 불리")
            s["reasons"].append(
                f"손절 {lv['stop_loss']:.2f} / 목표 {lv['target_price']:.2f}({lv['target_basis']}) · R:R {rr:.1f}({tag})")
        else:
            s["reasons"].append(f"손절 {lv['stop_loss']:.2f} (이탈 상태 — 목표 비적용)")
    elif highs:
        s["reasons"].append("가격 레벨 계산 불가(변동성/데이터 부족)")

    # --- 상대강도 (벤치마크 대비 초과수익) v3.6 ---
    s["benchmark"] = benchmark_for(ticker)
    rs = relative_strength(closes, bench_closes) if bench_closes else None
    s["rs_score"] = rs
    s["rs_label"] = rs_label_of(rs)
    rs_trend, rs_trend_label = rs_trend_of(closes, bench_closes) if bench_closes else (None, None)
    s["rs_trend"] = rs_trend
    s["rs_trend_label"] = rs_trend_label
    if rs is not None:
        tr = f", 추이 {rs_trend:+.1f}%p({rs_trend_label})" if rs_trend is not None else ""
        s["reasons"].append(f"상대강도 {s['benchmark']} 대비 {rs:+.1f}%p({s['rs_label']}){tr}")

    return s


def classify(signals):
    """스펙 2절 — 평가 순서 중요: 리스크(청산)를 먼저 본다. 애매하면 WATCH."""
    # 1) 청산 우선
    if signals["exit_triggered"] or signals["near_exit"]:
        return "EXIT_IMMINENT"
    # 2) 매수: 모든 게이트 통과
    vol_ok = signals["volume_confirmed"] in (True, None)   # 데이터 없으면 통과 처리
    if signals["price_ok"] and vol_ok \
       and signals["earnings_momentum"] == "UP" \
       and signals["valuation_ok"]:
        return "BUY"
    # 3) 나머지는 전부 관찰
    return "WATCH"


# ================================================================
# Supabase I/O
# ================================================================
def get_active_tickers():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_stocks", headers=HEADERS,
                     params={"active": "eq.true", "select": "ticker"}, timeout=30)
    r.raise_for_status()
    # 소유자 여럿이 같은 티커를 담을 수 있음 → 고유 티커만 (분류는 종목 기준)
    return list(dict.fromkeys(row["ticker"] for row in r.json()))


def get_prices(ticker):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_prices", headers=HEADERS,
                     params={"ticker": f"eq.{ticker}", "select": "trade_date,high,low,close,volume",
                             "order": "trade_date.desc", "limit": str(CONFIG["price_fetch_rows"])},
                     timeout=30)
    r.raise_for_status()
    rows = list(reversed(r.json()))   # 과거→최신
    highs = [float(x["high"]) for x in rows if x["high"] is not None]
    lows = [float(x["low"]) for x in rows if x["low"] is not None]
    closes = [float(x["close"]) for x in rows if x["close"] is not None]
    vols = [float(x["volume"]) for x in rows if x["volume"] is not None]
    return highs, lows, closes, vols


# 벤치마크 종가 캐시 (같은 지수를 여러 종목이 공유하므로 1회만 조회)
_bench_cache = {}

def get_bench_closes(symbol):
    if symbol in _bench_cache:
        return _bench_cache[symbol]
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_prices", headers=HEADERS,
                     params={"ticker": f"eq.{symbol}", "select": "close",
                             "order": "trade_date.desc", "limit": str(CONFIG["price_fetch_rows"])},
                     timeout=30)
    r.raise_for_status()
    closes = [float(x["close"]) for x in reversed(r.json()) if x["close"] is not None]
    _bench_cache[symbol] = closes
    return closes


def get_scores(ticker):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_score_history", headers=HEADERS,
                     params={"ticker": f"eq.{ticker}", "select": "check_date,diagnosis_score",
                             "order": "check_date"}, timeout=30)
    r.raise_for_status()
    return [x["diagnosis_score"] for x in r.json() if x["diagnosis_score"] is not None]


def _r(v, nd):
    """None-safe 반올림."""
    return round(v, nd) if v is not None else None


def save(ticker, state, s):
    payload = {
        "ticker": ticker,
        "state": state,
        "exit_triggered": bool(s["exit_triggered"]),
        "dist_to_exit_pct": round(s["dist_to_exit_pct"], 2) if s["dist_to_exit_pct"] is not None else None,
        "earnings_momentum": s["earnings_momentum"],
        "volume_confirmed": s["volume_confirmed"],
        "valuation_caution": bool(s["valuation_caution"]),
        "reasons": s["reasons"],
        "classified_at": "now()",
        # v3.6 가격 레벨 + 상대강도
        "atr":              _r(s.get("atr"), 4),
        "support_level":    _r(s.get("support_level"), 4),
        "resistance_level": _r(s.get("resistance_level"), 4),
        "stop_loss":        _r(s.get("stop_loss"), 4),
        "target_price":     _r(s.get("target_price"), 4),
        "rr_ratio":         _r(s.get("rr_ratio"), 2),
        "rs_score":         _r(s.get("rs_score"), 2),
        "rs_label":         s.get("rs_label"),
        "rs_trend":         _r(s.get("rs_trend"), 2),
        "rs_trend_label":   s.get("rs_trend_label"),
        "benchmark":        s.get("benchmark"),
        # v3.8 추세 구조 + 매물대
        "retrace_pct":      _r(s.get("retrace_pct"), 1),
        "swing_peak":       _r(s.get("swing_peak"), 4),
        "swing_trough":     _r(s.get("swing_trough"), 4),
        "trend_structure":  s.get("trend_structure"),
        "vp_poc":           _r(s.get("vp_poc"), 4),
        "vp_resistance":    _r(s.get("vp_resistance"), 4),
        "vp_support":       _r(s.get("vp_support"), 4),
    }
    r = requests.post(f"{SUPABASE_URL}/rest/v1/momentum_classification",
                      headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                      params={"on_conflict": "ticker"}, json=payload, timeout=30)
    r.raise_for_status()


def main():
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise SystemExit("SUPABASE_URL / SUPABASE_ANON_KEY 환경변수가 필요합니다.")
    tickers = get_active_tickers()
    tickers += [ix for ix in MARKET_INDICES if ix not in tickers]   # 시장 지수도 분류(시장 패널용)
    print(f"분류 대상 {len(tickers)}종목: {', '.join(tickers)}")
    ok = fail = 0
    counts = {"BUY": 0, "WATCH": 0, "EXIT_IMMINENT": 0}
    for i, t in enumerate(tickers, 1):
        try:
            highs, lows, closes, vols = get_prices(t)
            if len(closes) < 51:
                raise RuntimeError(f"가격 데이터 부족({len(closes)}일, 최소 51일)")
            bench = get_bench_closes(benchmark_for(t))
            sig = compute_signals(closes, lows, vols, get_scores(t), t,
                                  highs=highs, bench_closes=bench)
            state = classify(sig)
            save(t, state, sig)
            counts[state] += 1
            print(f"[{i}/{len(tickers)}] {t:8} {state:14} | {' · '.join(sig['reasons'][:3])}")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t:8} 실패: {e}")
            fail += 1
    print(f"완료 — 성공 {ok} / 실패 {fail} "
          f"(BUY {counts['BUY']} · WATCH {counts['WATCH']} · EXIT_IMMINENT {counts['EXIT_IMMINENT']})")
    if ok == 0 and tickers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
