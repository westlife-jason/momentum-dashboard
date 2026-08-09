-- ================================================================
-- momentum-dashboard · 신호 상태 저장 테이블 (신호 전환 알림용)
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (여러 번 실행해도 안전 — 이미 있으면 건너뜁니다)
-- ================================================================

-- 종목별 '직전 신호'를 1행씩 저장 → 매일 재계산해 바뀐 것만 알림
create table if not exists momentum_signal_state (
  ticker      text primary key,
  signal      text not null,               -- buy / pull / sell / wait
  updated_at  timestamptz default now()
);

-- RLS: 자동화(anon 키)가 읽고 쓸 수 있도록 (기존 테이블과 동일한 공개 정책)
alter table momentum_signal_state enable row level security;

drop policy if exists "signal_state anon read"   on momentum_signal_state;
drop policy if exists "signal_state anon insert" on momentum_signal_state;
drop policy if exists "signal_state anon update" on momentum_signal_state;

create policy "signal_state anon read"
  on momentum_signal_state for select using (true);
create policy "signal_state anon insert"
  on momentum_signal_state for insert with check (true);
create policy "signal_state anon update"
  on momentum_signal_state for update using (true) with check (true);
