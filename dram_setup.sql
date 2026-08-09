-- ================================================================
-- momentum-dashboard · DRAM 사이클 모니터 (스팟/계약가격)
-- Supabase → SQL Editor 에 붙여넣고 [Run] 한 번만 실행하세요.
-- (여러 번 실행해도 안전)
--
-- 관리자가 주/월 1회 스팟·계약가격을 입력하면,
-- 대시보드가 추세 차트 + "스팟<계약 = 사이클 종료" 신호를 자동 표시합니다.
-- ================================================================

create table if not exists dram_prices (
  id          bigint generated always as identity primary key,
  price_date  date        not null,             -- 가격 기준일
  product     text        not null default 'DDR4 8Gb',  -- 추적 제품
  spot        numeric     not null,             -- 현물가격
  contract    numeric     not null,             -- 고정(계약)가격
  note        text,
  created_at  timestamptz default now(),
  unique (product, price_date)                  -- 같은 날 재입력하면 덮어쓰기
);

create index if not exists idx_dram_product_date on dram_prices (product, price_date);

-- RLS: 대시보드(anon 키)가 읽고 쓸 수 있도록 (기존 테이블과 동일한 공개 정책)
alter table dram_prices enable row level security;

drop policy if exists "dram anon read"   on dram_prices;
drop policy if exists "dram anon insert" on dram_prices;
drop policy if exists "dram anon update" on dram_prices;

create policy "dram anon read"   on dram_prices for select using (true);
create policy "dram anon insert" on dram_prices for insert with check (true);
create policy "dram anon update" on dram_prices for update using (true) with check (true);
