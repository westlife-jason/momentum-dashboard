"""
모멘텀 대시보드 - 한국 종목 진단점수 자동계산 (DART OpenAPI)
- 대상: momentum_stocks 중 active=true 이면서 티커가 '6자리 숫자'인 종목(한국주식)
- 재무제표: DART fnlttSinglAcntAll (단일회사 전체 재무제표, 최근 사업보고서)
- 채점 기준은 미국(update_scores.py / scoreFromMetrics)과 동일한 100점 모델
- 결과: momentum_stocks 갱신 + momentum_score_history 이력 upsert (미국과 동일 경로)
- 시크릿 필요: SUPABASE_URL, SUPABASE_ANON_KEY, DART_API_KEY
- 알려진 한계: DART 연간 사업보고서 기준(TTM 아님). 매출총이익 미표기 시 (매출액-매출원가)로 산출.
              발행주식수는 당기순이익/EPS로 근사(P/FCF 계산용).
"""
import os
import io
import time
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

import requests

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_ANON_KEY"]
DART_KEY     = os.environ["DART_API_KEY"]

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

# ---------- 공통 유틸 ----------
def is_kr(ticker: str) -> bool:
    return ticker.isdigit() and len(ticker) == 6

def money(v):
    v = (v or "").replace(",", "").strip()
    try:
        return int(v)
    except ValueError:
        return None

def norm(s):
    return (s or "").replace(" ", "").replace("\t", "")

def grade(val, bands):
    if val is None:
        return 0
    for th, pt in bands:
        if val >= th:
            return pt
    return 0

def grade_low(val, bands):
    if val is None:
        return 0
    for th, pt in bands:
        if val <= th:
            return pt
    return 0

# ---------- DART ----------
def load_corp_map():
    """전체 상장사 corp_code 매핑: {6자리 종목코드: 8자리 corp_code}."""
    r = requests.get("https://opendart.fss.or.kr/api/corpCode.xml",
                     params={"crtfc_key": DART_KEY}, timeout=60)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    root = ET.fromstring(z.read(z.namelist()[0]))
    m = {}
    for el in root.iter("list"):
        sc = (el.findtext("stock_code") or "").strip()
        if sc:
            m[sc] = el.findtext("corp_code").strip()
    return m

def fetch_fs(corp_code):
    """최근 사업보고서를 연도·연결/별도 순으로 시도해 첫 유효 응답 반환."""
    this_year = date.today().year
    for year in (this_year - 1, this_year - 2):
        for fs_div in ("CFS", "OFS"):
            j = requests.get(
                "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json",
                params={"crtfc_key": DART_KEY, "corp_code": corp_code,
                        "bsns_year": str(year), "reprt_code": "11011", "fs_div": fs_div},
                timeout=30,
            ).json()
            if j.get("status") == "000" and j.get("list"):
                return year, fs_div, j["list"]
    return None, None, None

def build_index(rows):
    """[(sj_div, 정규화계정명, 당기, 전기), ...]"""
    return [(r.get("sj_div"), norm(r.get("account_nm")),
             money(r.get("thstrm_amount")), money(r.get("frmtrm_amount"))) for r in rows]

def pick(idx, sjs, pats):
    """sj_div가 sjs에 속하는 항목 중, 계정명이 pats와 (정확→부분)일치하는 첫 값."""
    for p in pats:
        for sj, n, t, f in idx:
            if sj in sjs and n == p:
                return t, f
    for p in pats:
        for sj, n, t, f in idx:
            if sj in sjs and p in n:
                return t, f
    return None, None

# ---------- 채점 (미국과 동일 밴드) ----------
def score_from_dart(idx, price):
    IS = ("IS", "CIS")   # 손익: 회사에 따라 IS 또는 CIS
    rev, rev0 = pick(idx, IS, ["매출액", "수익(매출액)", "영업수익"])
    cogs, _   = pick(idx, IS, ["매출원가"])
    gp, _     = pick(idx, IS, ["매출총이익"])
    op, _     = pick(idx, IS, ["영업이익"])
    ni, _     = pick(idx, IS, ["당기순이익"])
    eps, eps0 = pick(idx, IS, ["기본주당순이익", "기본주당이익", "주당순이익", "주당이익"])
    debt, _   = pick(idx, ("BS",), ["부채총계"])
    eq, _     = pick(idx, ("BS",), ["자본총계"])
    ca, _     = pick(idx, ("BS",), ["유동자산"])
    cl, _     = pick(idx, ("BS",), ["유동부채"])
    ocf, _    = pick(idx, ("CF",), ["영업활동현금흐름", "영업활동으로인한현금흐름"])
    capex, _  = pick(idx, ("CF",), ["유형자산의취득"])
    if gp is None and rev is not None and cogs is not None:
        gp = rev - cogs

    rev_g = (rev - rev0) / rev0 * 100 if (rev is not None and rev0) else None
    eps_g = (eps - eps0) / eps0 * 100 if (eps is not None and eps0) else None
    op_m  = op / rev * 100 if (op is not None and rev) else None
    roe   = ni / eq * 100 if (ni is not None and eq) else None
    de    = debt / eq if (debt is not None and eq) else None
    cr    = ca / cl if (ca is not None and cl) else None
    gm    = gp / rev * 100 if (gp is not None and rev) else None
    fcf   = ocf - capex if (ocf is not None and capex is not None) else None
    shares = ni / eps if (ni and eps) else None
    pfcf  = (shares * price) / fcf if (shares and price and fcf and fcf > 0) else None

    growth = grade(rev_g, [(40,18),(25,15),(15,11),(5,7),(0,3)]) + grade(eps_g, [(50,12),(25,9),(10,6),(0,3)])
    profit = grade(op_m, [(25,13),(15,10),(5,7),(0,4)]) + grade(roe, [(20,12),(10,9),(0,5)])
    safety = grade_low(de, [(0.3,10),(0.8,8),(1.5,5),(999,2)]) + grade(cr, [(2,10),(1.5,8),(1,5),(0,2)])
    cash   = (8 if (fcf is not None and fcf > 0) else 0) + (grade_low(pfcf, [(40,7),(80,4),(9999,2)]) if pfcf else 0)
    moat   = grade(gm, [(50,10),(35,7),(20,4),(0,1)])
    return {"total": growth+profit+safety+cash+moat,
            "growth": growth, "profit": profit, "safety": safety, "cash": cash, "moat": moat}

# ---------- Supabase ----------
def get_active_kr_tickers():
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_stocks", headers=HEADERS,
                     params={"active": "eq.true", "select": "ticker"}, timeout=30)
    r.raise_for_status()
    return [row["ticker"] for row in r.json() if is_kr(row["ticker"])]

def latest_price(ticker):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/momentum_prices", headers=HEADERS,
                     params={"ticker": f"eq.{ticker}", "select": "close",
                             "order": "trade_date.desc", "limit": "1"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return float(data[0]["close"]) if data else None

def save_stock_and_history(ticker, sc):
    detail = {k: sc[k] for k in ("growth", "profit", "safety", "cash", "moat")}
    today = date.today().isoformat()
    r = requests.patch(f"{SUPABASE_URL}/rest/v1/momentum_stocks", headers=HEADERS,
                       params={"ticker": f"eq.{ticker}"},
                       json={"diagnosis_score": sc["total"], "score_detail": detail, "score_updated": today},
                       timeout=30)
    r.raise_for_status()
    h = requests.post(f"{SUPABASE_URL}/rest/v1/momentum_score_history",
                      headers={**HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                      params={"on_conflict": "ticker,check_date"},
                      json={"ticker": ticker, "check_date": today,
                            "diagnosis_score": sc["total"], "score_detail": detail}, timeout=30)
    h.raise_for_status()

def main():
    tickers = get_active_kr_tickers()
    print(f"한국 종목 {len(tickers)}개: {', '.join(tickers) if tickers else '(없음)'}")
    if not tickers:
        return
    corp_map = load_corp_map()
    ok, fail = 0, 0
    for i, t in enumerate(tickers, 1):
        try:
            corp = corp_map.get(t)
            if not corp:
                raise RuntimeError("corp_code 없음")
            year, fs_div, rows = fetch_fs(corp)
            if not rows:
                raise RuntimeError("재무제표 없음")
            sc = score_from_dart(build_index(rows), latest_price(t))
            save_stock_and_history(t, sc)
            print(f"[{i}/{len(tickers)}] {t} = {sc['total']}점 "
                  f"(성{sc['growth']} 수{sc['profit']} 안{sc['safety']} 현{sc['cash']} 독{sc['moat']}) "
                  f"[{year} {fs_div}]")
            ok += 1
        except Exception as e:
            print(f"[{i}/{len(tickers)}] {t} 실패: {e}")
            fail += 1
        time.sleep(0.5)
    print(f"완료 — 성공 {ok} / 실패 {fail}")
    if ok == 0 and tickers:
        raise SystemExit(1)

if __name__ == "__main__":
    main()
