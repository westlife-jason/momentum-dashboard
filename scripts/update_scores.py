"""
모멘텀 대시보드 v2 - 주간 진단점수 자동 갱신
GitHub Actions가 매주 월요일 실행합니다. (수동 실행: python scripts/update_scores.py)
채점 기준은 대시보드 HTML의 scoreFromMetrics()와 동일합니다.
"""
import os, time, requests
from datetime import date

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
FINNHUB_KEY  = os.environ["FINNHUB_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

def grade(val, bands):
    """값이 클수록 좋은 지표. bands: [(기준, 점수)] 높은 기준부터"""
    if val is None:
        return 0
    for th, pt in bands:
        if val >= th:
            return pt
    return 0

def grade_low(val, bands):
    """값이 작을수록 좋은 지표. bands: [(기준, 점수)] 낮은 기준부터"""
    if val is None:
        return 0
    for th, pt in bands:
        if val <= th:
            return pt
    return 0

def score_from_metrics(m):
    growth = (
        grade(m.get("revenueGrowthTTMYoy"), [(40,18),(25,15),(15,11),(5,7),(0,3)]) +
        grade(m.get("epsGrowthTTMYoy"),     [(50,12),(25,9),(10,6),(0,3)])
    )
    profit = (
        grade(m.get("operatingMarginTTM"), [(25,13),(15,10),(5,7),(0,4)]) +
        grade(m.get("roeTTM"),             [(20,12),(10,9),(0,5)])
    )
    safety = (
        grade_low(m.get("totalDebt/totalEquityQuarterly"), [(0.3,10),(0.8,8),(1.5,5),(999,2)]) +
        grade(m.get("currentRatioQuarterly"), [(2,10),(1.5,8),(1,5),(0,2)])
    )
    fcf_ps = m.get("freeCashFlowPerShareTTM")
    pfcf   = m.get("pfcfShareTTM")
    cash = (8 if (fcf_ps is not None and fcf_ps > 0) else 0)
    if pfcf is not None and pfcf > 0:
        cash += grade_low(pfcf, [(40,7),(80,4),(9999,2)])
    moat = grade(m.get("grossMarginTTM"), [(50,10),(35,7),(20,4),(0,1)])
    return {
        "total": growth + profit + safety + cash + moat,
        "growth": growth, "profit": profit,
        "safety": safety, "cash": cash, "moat": moat,
    }

def get_active_tickers():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/momentum_stocks",
        headers=HEADERS,
        params={"active": "eq.true", "select": "ticker"},
        timeout=30,
    )
    r.raise_for_status()
    return [row["ticker"] for row in r.json()]

def fetch_metrics(ticker):
    r = requests.get(
        "https://finnhub.io/api/v1/stock/metric",
        params={"symbol": ticker, "metric": "all", "token": FINNHUB_KEY},
        timeout=30,
    )
    j = r.json()
    m = j.get("metric") or {}
    if not m:
        raise RuntimeError("지표 없음")
    return m

def update_stock(ticker, sc):
    r = requests.patch(
        f"{SUPABASE_URL}/rest/v1/momentum_stocks",
        headers=HEADERS,
        params={"ticker": f"eq.{ticker}"},
        json={
            "diagnosis_score": sc["total"],
            "score_detail": {k: sc[k] for k in ("growth","profit","safety","cash","moat")},
            "score_updated": date.today().isoformat(),
        },
        timeout=30,
    )
    r.raise_for_status()

def main():
    tickers = get_active_tickers()
    print(f"대상 종목 {len(tickers)}개")
    ok, fail = 0, 0
    for i, t in enumerate(tickers, 1):
        try:
            sc = score_from_metrics(fetch_metrics(t))
            update_stock(t, sc)
            print(f"[{i}/{len(tickers)}] {t} = {sc['total']}점 "
                  f"(성{sc['growth']} 수{sc['profit']} 안{sc['safety']} 현{sc['cash']} 독{sc['moat']})")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t} 실패: {e}")
            fail += 1
        time.sleep(1.2)  # Finnhub 무료: 분당 60회
    print(f"완료 — 성공 {ok} / 실패 {fail}")
    if ok == 0 and tickers:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
