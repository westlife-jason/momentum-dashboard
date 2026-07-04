"""
모멘텀 대시보드 - 신호 전환 알림 (텔레그램)
- 매일 실행: 모든 활성 종목의 모멘텀 신호를 재계산 → 직전 신호와 비교 → 바뀐 종목만 알림
- 신호 로직은 대시보드 index.html의 computeStock()과 동일 (정배열 + 기준선 이탈 매도 + 눌림목)
- 첫 실행(상태 테이블 비어있음)은 알림 대신 현재 상태를 저장 + 1회 '알림 켜짐' 확인 메시지
- 시크릿 필요: SUPABASE_URL, SUPABASE_ANON_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import os
from datetime import date

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
TG_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT      = os.environ["TELEGRAM_CHAT_ID"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

PULLBACK_NEAR = 2.0   # 이평선 ±2% 이내면 눌림목 접근

LABEL = {
    "buy":  "🟢 매수·보유",
    "pull": "🟡 눌림목 대기",
    "sell": "🔴 매도 신호",
    "wait": "⚪ 관망",
}

# ---------- 신호 계산 (index.html computeStock 이식) ----------
def sma(closes, n):
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n

def compute_signal(closes, baseline_ma):
    n = len(closes)
    if n < 61:
        return "wait"
    close = closes[-1]
    ma20, ma50, ma60 = sma(closes, 20), sma(closes, 50), sma(closes, 60)
    base = ma60 if baseline_ma == 60 else ma50
    uptrend = close > base and ma20 > ma50
    def near(ma):
        return abs(close / ma - 1) * 100 <= PULLBACK_NEAR
    if close < base:
        return "sell"
    if uptrend and (near(ma20) or near(ma50)):
        return "pull"
    if uptrend:
        return "buy"
    return "wait"

# ---------- Supabase ----------
def get_active_stocks():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_stocks", headers=HEADERS,
                     params={"active": "eq.true", "select": "ticker,name,baseline_ma", "order": "ticker"},
                     timeout=30)
    r.raise_for_status()
    return r.json()

def get_closes(ticker):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_prices", headers=HEADERS,
                     params={"ticker": f"eq.{ticker}", "select": "close",
                             "order": "trade_date.desc", "limit": "70"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    return [float(x["close"]) for x in reversed(rows)]   # 과거→최신

def get_state():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_signal_state", headers=HEADERS,
                     params={"select": "ticker,signal"}, timeout=30)
    r.raise_for_status()
    return {row["ticker"]: row["signal"] for row in r.json()}

def save_state(ticker, signal):
    requests.post(f"{SUPABASE_URL}/rest/v1/momentum_signal_state",
                  headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                  params={"on_conflict": "ticker"},
                  json={"ticker": ticker, "signal": signal, "updated_at": "now()"},
                  timeout=30).raise_for_status()

def market_note():
    """참고용 시장 체제 (bear_market_checks 최신 1건)."""
    try:
        r = requests.get(f"{SUPABASE_URL}/rest/v1/bear_market_checks", headers=HEADERS,
                         params={"select": "grade,check_date", "order": "check_date.desc", "limit": "1"}, timeout=30)
        r.raise_for_status()
        d = r.json()
        return f"⚠️ 시장 체제: {d[0].get('grade','-')} (참고)" if d else ""
    except Exception:
        return ""

# ---------- 텔레그램 ----------
def send_telegram(text):
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=30)
    r.raise_for_status()

# ---------- 메인 ----------
def main():
    stocks = get_active_stocks()
    prev = get_state()
    first_run = (len(prev) == 0)
    changes, current = [], []

    for s in stocks:
        t, name = s["ticker"], s["name"]
        closes = get_closes(t)
        sig = compute_signal(closes, s.get("baseline_ma") or 50)
        current.append((name, sig))
        old = prev.get(t)
        if (not first_run) and old and old != sig:
            changes.append(f"{LABEL[sig][:2]} <b>{name}</b>: {LABEL[old]} → {LABEL[sig]}")
        save_state(t, sig)

    today = date.today().isoformat()
    if first_run:
        lines = "\n".join(f"• {name}: {LABEL[sig]}" for name, sig in current)
        send_telegram(f"✅ <b>모멘텀 신호 알림이 켜졌습니다</b> ({today})\n\n현재 상태:\n{lines}\n\n"
                      f"앞으로 신호가 <b>바뀔 때만</b> 알려드립니다.")
        print(f"첫 실행 — 현재 상태 {len(current)}건 저장 + 확인 메시지 발송")
    elif changes:
        body = "\n".join(changes)
        note = market_note()
        send_telegram(f"📊 <b>모멘텀 신호 변화</b> ({today})\n\n{body}" + (f"\n\n{note}" if note else ""))
        print(f"신호 변화 {len(changes)}건 알림 발송")
    else:
        print("신호 변화 없음 — 알림 없음")

if __name__ == "__main__":
    main()
