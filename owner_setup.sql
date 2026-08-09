-- ================================================================
-- momentum-dashboard v3.2 · 소유자(owner)별 종목 지원
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (여러 번 실행해도 안전)
--
-- 효과: momentum_stocks 를 사람(owner)별로 나눕니다.
--       기존 종목은 전부 owner='jason' 이 됩니다.
--       시세/점수 테이블은 그대로(종목 기준 공유) — 바꾸지 않습니다.
-- ================================================================

-- 1) owner 컬럼 추가 (기존 행은 자동으로 'jason')
alter table momentum_stocks
  add column if not exists owner text not null default 'jason';

-- 2) 기본키를 (owner, ticker) 복합키로 변경
--    → 서로 다른 사람이 같은 종목(예: 삼성전자)을 각자 담을 수 있게 됨
do $$
declare pkname text;
begin
  select conname into pkname
    from pg_constraint
   where conrelid = 'public.momentum_stocks'::regclass
     and contype = 'p';
  if pkname is not null then
    execute format('alter table public.momentum_stocks drop constraint %I', pkname);
  end if;
end $$;

alter table momentum_stocks
  add constraint momentum_stocks_pkey primary key (owner, ticker);

-- 3) 소유자별 조회 인덱스
create index if not exists idx_stocks_owner on momentum_stocks (owner);
