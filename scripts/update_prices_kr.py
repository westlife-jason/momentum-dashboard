"""
모멘텀 대시보드 - 한국 종목 일일 시세 수집 (FinanceDataReader)
- 대상: momentum_stocks 중 active=true 이면서 티커가 '6자리 숫자'인 종목 (한국주식)
- 무료 무키(無key): FinanceDataReader가 네이버/KRX 데이터를 가져옵니다.
- GitHub Actions가 평일 장마감 후 실행. (수동: python scripts/update_prices_kr.py)
- 미국 종목 시세(update_prices.py, Twelve Data)와는 별도 경로입니다.
"""
import os
from datetime import date, timedelta

import requests
import FinanceDataReader as fdr

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# 최근 약 300일치(≈200 거래일)를 받아 이동평균 60일 + 차트 120일에 충분하도록
LOOKBACK_DAYS = 300


def is_kr(ticker: str) -> bool:
    """6자리 숫자 티커 = 한국주식으로 간주."""
    return ticker.isdigit() and len(ticker) == 6


def get_kr_tickers():
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/momentum_stocks",
        headers=HEADERS,
        params={"active": "eq.true", "select": "ticker"},
        timeout=30,
    )
    r.raise_for_status()
    return [row["ticker"] for row in r.json() if is_kr(row["ticker"])]


def fetch_and_upsert(ticker: str) -> int:
    start = (date.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    df = fdr.DataReader(ticker, start)
    if df is None or df.empty:
        raise RuntimeError("시세 데이터 없음")

    rows = []
    for idx, r in df.iterrows():
        close = r.get("Close")
        if close is None or close != close:  # NaN 방어
            continue
        vol = r.get("Volume")
        rows.append({
            "ticker": ticker,
            "trade_date": idx.date().isoformat(),
            "open":  float(r["Open"])  if r.get("Open")  == r.get("Open")  else None,
            "high":  float(r["High"])  if r.get("High")  == r.get("High")  else None,
            "low":   float(r["Low"])   if r.get("Low")   == r.get("Low")   else None,
            "close": float(close),
            "volume": int(vol) if (vol is not None and vol == vol) else None,
        })

    if not rows:
        raise RuntimeError("유효한 행 없음")

    resp = requests.post(
        f"{SUPABASE_URL}/rest/v1/momentum_prices",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
        params={"on_conflict": "ticker,trade_date"},
        json=rows,
        timeout=90,
    )
    resp.raise_for_status()
    return len(rows)


def main():
    tickers = get_kr_tickers()
    print(f"한국 종목 {len(tickers)}개: {', '.join(tickers) if tickers else '(없음)'}")
    ok, fail = 0, 0
    for i, t in enumerate(tickers, 1):
        try:
            n = fetch_and_upsert(t)
            print(f"[{i}/{len(tickers)}] {t} = {n}일치 저장")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t} 실패: {e}")
            fail += 1
    print(f"완료 — 성공 {ok} / 실패 {fail}")
    if ok == 0 and tickers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
