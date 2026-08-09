-- ================================================================
-- momentum-dashboard v3.7 · 상대강도(RS) 추이 필드 추가
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (momentum_classification 에 컬럼 2개만 추가 — 안전, 여러 번 실행 OK)
--
-- rs_trend: 현재 RS − 20거래일(≈1개월) 전 RS (%p). 양수=개선, 음수=악화
-- ================================================================

alter table momentum_classification
  add column if not exists rs_trend       numeric,   -- RS 변화폭(%p): +개선 / −악화
  add column if not exists rs_trend_label text;       -- '개선' | '유지' | '악화'
