-- ================================================================
-- momentum-dashboard v3.8 · 추세 구조(되돌림/저점구조) + 매물대(볼륨 프로파일)
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (momentum_classification 에 컬럼만 추가 — 안전, 여러 번 실행 OK)
-- ================================================================

alter table momentum_classification
  -- 되돌림(Retracement): 고점→저점 하락의 몇 %를 회복했나
  add column if not exists retrace_pct     numeric,   -- (현재-저점)/(고점-저점) %
  add column if not exists swing_peak      numeric,   -- 최근 고점
  add column if not exists swing_trough    numeric,   -- 고점 이후 저점
  -- 저점 구조: '상승구조'(저점↑) | '하락구조'(저점↓) | '횡보'
  add column if not exists trend_structure text,
  -- 매물대(Volume Profile): 거래량 밀집 가격
  add column if not exists vp_poc          numeric,   -- 최대 거래 가격대(Point of Control)
  add column if not exists vp_resistance   numeric,   -- 현재가 위 최근접 매물벽(저항)
  add column if not exists vp_support      numeric;   -- 현재가 아래 최근접 매물벽(지지)
