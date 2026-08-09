-- ================================================================
-- momentum-dashboard v3 · 진단점수 이력 테이블
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (여러 번 실행해도 안전 — 이미 있으면 건너뜁니다)
-- ================================================================

-- 1) 이력 테이블: 종목별 · 날짜별로 진단점수를 1행씩 쌓는다
create table if not exists momentum_score_history (
  id              bigint generated always as identity primary key,
  ticker          text        not null,
  check_date      date        not null,          -- 점수 계산 기준일
  diagnosis_score integer     not null,          -- 총점 (0~100)
  score_detail    jsonb,                          -- {growth,profit,safety,cash,moat}
  created_at      timestamptz default now(),
  unique (ticker, check_date)                     -- 같은 날 재계산하면 덮어쓰기(upsert)
);

-- 2) 조회 속도용 인덱스 (종목 → 날짜순)
create index if not exists idx_score_history_ticker_date
  on momentum_score_history (ticker, check_date);

-- 3) RLS: 대시보드(anon 키)가 읽고 쓸 수 있도록 허용
--    기존 momentum_stocks / momentum_prices 와 동일한 공개 정책입니다.
alter table momentum_score_history enable row level security;

drop policy if exists "score_history anon read"   on momentum_score_history;
drop policy if exists "score_history anon insert" on momentum_score_history;
drop policy if exists "score_history anon update" on momentum_score_history;

create policy "score_history anon read"
  on momentum_score_history for select using (true);
create policy "score_history anon insert"
  on momentum_score_history for insert with check (true);
create policy "score_history anon update"
  on momentum_score_history for update using (true) with check (true);
