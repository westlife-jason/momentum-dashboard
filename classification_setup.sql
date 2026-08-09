-- ================================================================
-- momentum-dashboard · 3상태 분류 레이어 (BUY / WATCH / EXIT_IMMINENT)
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (여러 번 실행해도 안전)
--
-- 설계 메모: momentum_stocks 는 (owner, ticker) 기준이지만
--            분류는 시세·점수와 같이 '종목(ticker) 기준'이므로 별도 테이블로 둔다.
--            → 여러 소유자가 같은 종목을 담아도 분류는 1번만 계산·저장.
-- ================================================================

create table if not exists momentum_classification (
  ticker             text primary key,
  state              text        not null,          -- 'BUY' | 'WATCH' | 'EXIT_IMMINENT'
  exit_triggered     boolean     not null default false,
  dist_to_exit_pct   numeric,                        -- 청산선까지 거리(%) — 계산불가 시 null
  earnings_momentum  text,                           -- 'UP' | 'FLAT' | 'DOWN'
  volume_confirmed   boolean,
  valuation_caution  boolean     not null default false,  -- 사이클 종목 등
  reasons            jsonb,                          -- 사람이 읽는 근거 문자열 배열
  classified_at      timestamptz default now()
);

create index if not exists idx_classification_state on momentum_classification (state);

-- RLS: 자동화(anon 키)가 읽고 쓸 수 있도록 (기존 테이블과 동일한 공개 정책)
alter table momentum_classification enable row level security;

drop policy if exists "classification anon read"   on momentum_classification;
drop policy if exists "classification anon insert" on momentum_classification;
drop policy if exists "classification anon update" on momentum_classification;

create policy "classification anon read"
  on momentum_classification for select using (true);
create policy "classification anon insert"
  on momentum_classification for insert with check (true);
create policy "classification anon update"
  on momentum_classification for update using (true) with check (true);
