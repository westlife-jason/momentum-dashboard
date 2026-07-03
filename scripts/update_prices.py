"""
모멘텀 대시보드 v2 - 일일 시세 자동 수집
GitHub Actions가 매일 실행합니다. (수동 실행: python scripts/update_prices.py)
"""
import os, time, requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
TWELVE_KEY   = os.environ["TWELVE_DATA_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
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

def fetch_prices(ticker, bars=30):
    r = requests.get(
        "https://api.twelvedata.com/time_series",
        params={"symbol": ticker, "interval": "1day",
                "outputsize": bars, "apikey": TWELVE_KEY},
        timeout=30,
    )
    j = r.json()
    if j.get("status") == "error" or "values" not in j:
        raise RuntimeError(j.get("message", "no data"))
    rows = []
    for v in j["values"]:
        rows.append({
            "ticker": ticker,
            "trade_date": v["datetime"],
            "open": float(v["open"]),
            "high": float(v["high"]),
            "low": float(v["low"]),
            "close": float(v["close"]),
            "volume": int(float(v["volume"])) if v.get("volume") else None,
        })
    return rows

def upsert_prices(rows):
    r = requests.post(
        f"{SUPABASE_URL}/rest/v1/momentum_prices",
        headers={**HEADERS, "Prefer": "resolution=merge-duplicates"},
        params={"on_conflict": "ticker,trade_date"},
        json=rows,
        timeout=30,
    )
    r.raise_for_status()

def main():
    tickers = get_active_tickers()
    print(f"대상 종목 {len(tickers)}개: {', '.join(tickers)}")
    ok, fail = 0, 0
    for i, t in enumerate(tickers, 1):
        try:
            rows = fetch_prices(t)
            upsert_prices(rows)
            print(f"[{i}/{len(tickers)}] {t} OK ({len(rows)}일)")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t} 실패: {e}")
            fail += 1
        time.sleep(8)  # Twelve Data 무료 요금제: 분당 8회 제한 대응
    print(f"완료 — 성공 {ok} / 실패 {fail}")
    if ok == 0 and tickers:
        raise SystemExit(1)  # 전부 실패하면 Actions에 빨간불 표시

if __name__ == "__main__":
    main()

