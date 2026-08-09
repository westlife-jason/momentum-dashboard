-- ================================================================
-- momentum-dashboard v3.6 · 가격 레벨(ATR) + 상대강도(RS) 필드 추가
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (기존 momentum_classification 테이블에 컬럼만 추가 — 안전, 여러 번 실행 OK)
-- ================================================================

alter table momentum_classification
  add column if not exists atr              numeric,   -- ATR(14), 변동성
  add column if not exists support_level    numeric,   -- 지지선(전저점/수동)
  add column if not exists resistance_level numeric,   -- 저항선(전고점) — 목표가 근거
  add column if not exists stop_loss        numeric,   -- 손절가 (ATR 기반, 지지선 반영)
  add column if not exists target_price     numeric,   -- 목표가 (저항선 or R배수)
  add column if not exists rr_ratio         numeric,   -- 손익비 = (목표-현재)/(현재-손절)
  add column if not exists rs_score         numeric,   -- 상대강도: 벤치 대비 초과수익 %p
  add column if not exists rs_label         text,      -- '강세'|'중립'|'약세'
  add column if not exists benchmark        text;      -- 비교 벤치마크(SOXX/SPY/KS11 등)
