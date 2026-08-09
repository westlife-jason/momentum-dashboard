# momentum-dashboard 프로젝트 지침 (CLAUDE.md)

## 프로젝트 개요
미국 주식 모멘텀 투자전략 대시보드. "좋은 기업(진단점수) + 적정 가치 + 살아있는 모멘텀" 3조건 동시 충족 시 매수하는 전략을 시각화한다.
기존 `bear-market-dashboard`(약세장 조기경보)의 자매 프로젝트이며, 두 프로젝트는 **별도 배포**로 유지한다 (코드 통합 금지).

## 사용자(소유자) 정보
- GitHub: `westlife-jason` (Jason)
- **코딩 초보자**: 설명은 쉬운 한국어로, 단계별로. 터미널 명령어는 복사해서 바로 쓸 수 있게 제공.
- 답변과 코드 주석은 한국어 사용.

## 기술 스택 & 배포 파이프라인
- 프론트엔드: **단일 index.html 파일** (프레임워크 없음, 순수 HTML/CSS/JS)
- 데이터베이스: Supabase (REST API로 접근)
- 배포: GitHub main 브랜치 push → Netlify 자동 재배포
- 자동화: GitHub Actions + Python 스크립트 (`requests` 라이브러리만 사용)
- ⚠️ Netlify 배포 지연이 종종 있음 → index.html에 **버전 마커** (예: `<!-- v2.1 -->`)를 넣어 배포 확인하는 관례 유지

## 저장소 구조
```
momentum-dashboard/
├── index.html                          # 대시보드 전체 (단일 파일)
├── .github/workflows/
│   ├── update-prices.yml               # 일일 시세 수집
│   └── update-scores.yml               # 주간 진단점수 갱신
└── scripts/
    ├── update_prices.py                # Twelve Data API → Supabase
    └── update_scores.py                # Finnhub API → Supabase
```
⚠️ 과거에 `.github/workflows/` 안에 폴더가 중첩 생성된 사고가 있었음. 경로 작업 시 최상위 기준 확인할 것.

## 외부 API & 시크릿
GitHub 저장소 시크릿 4개 (Settings → Secrets and variables → Actions):
- `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `TWELVE_DATA_KEY`, `FINNHUB_KEY`

API 제약:
- Twelve Data: 무료 티어, 일일 시세 수집용
- Finnhub: 무료 티어 60콜/분, 진단점수용 (호출 간 딜레이 유지)

## 자동화 스케줄
- 일일 시세 수집: 월~금 22:00 UTC = 화~토 07:00 KST (미국 장 마감 반영)
- 주간 진단점수 갱신: 일 23:00 UTC = 월 08:00 KST
- 둘 다 `workflow_dispatch` 수동 실행 가능
- GitHub 무료 스케줄은 수분~수십분 지연될 수 있음 (정상)
- Actions의 "Node.js 20 deprecated" 경고는 무해함 (GitHub 내부 액션 문제, 무시)

## 데이터 모델 (Supabase)
- 시세 테이블: `(ticker, trade_date)` 기준 upsert (충돌 해결)
- 약세장 대시보드의 `bear_market_checks` 테이블을 **읽기 전용**으로 참조
  - 컬럼: `check_date`, `grade`, `red_count`, `yellow_count`, `green_count`
  - 시장이 위험 등급이면 신규 매수 신호 잠금(lock) 처리
  - ⚠️ 이 테이블은 절대 수정하지 말 것 (bear-market-dashboard 소유)

## 핵심 로직

### 모멘텀 신호 4단계
1. **매수/보유**: 상승 추세 + 주가가 기준 이평선 위
2. **눌림목 관찰**: 주가가 20일 또는 50일 이평선 ±2% 이내
3. **매도 신호**: 종가 기준 기준 이평선 하향 이탈 (기계적 집행, 재량 배제)
4. **대기**: 데이터 부족 또는 이평선 정배열 아님

각 종목 카드에 "눌림목 레일" 시각화 포함 (1차 눌림 = 20일선, 2차 눌림 = 50일선).

### 진단점수 100점 모델 (Finnhub 데이터 기반 자체 구축)
- 성장성 30점 (TTM 매출/EPS 성장)
- 수익성 25점 (영업이익률, ROE)
- 재무 안전성 20점 (부채비율, 유동비율)
- 현금창출 15점 (FCF 흑자 여부, P/FCF)
- 경제적 해자 근사 10점 (매출총이익률)
- 알려진 한계: 현재/과거 재무만 사용 (선행 컨센서스 미반영) → AMD처럼 성장 기대주는 벤치마크보다 낮게 나올 수 있음 (버그 아님)

## 현재 종목
- 미국(6): AMD, MU, SNDK, CRDO, TLN, TSLA (TSLA는 대조군)
- 한국(4): 삼성전자(005930), SK하이닉스(000660), HPSP(403870), 대한전선(001440)
- 티커가 6자리 숫자면 한국주식으로 자동 인식 (원화 표시 + FinanceDataReader 시세)

## 현재 상태 (2026-07-04 기준)
- ✅ v1: 신호 엔진 + 수동 시세 갱신 버튼
- ✅ v1.1: Finnhub 기반 진단점수 엔진
- ✅ v2: GitHub Actions 자동화 완료, "일일 시세 수집" 수동 테스트 성공 (초록 체크)
- ✅ v2: "주간 진단점수 갱신" 워크플로우 수동 테스트 성공 (2026-07-04, 25초, 초록 체크)
- ✅ v3(진단점수 이력 저장+추세 차트): 배포 완료
  - Supabase 새 테이블 `momentum_score_history` 생성 (`score_history_setup.sql`), 첫 데이터 6종목 적재
  - index.html: 상세 영역에 "진단점수 추세" 누적 막대차트(성장/수익/안전/현금/독점) 추가
  - scripts/update_scores.py: 매주 자동화가 momentum_stocks 갱신 + 이력 upsert
  - 이력 테이블 없어도 대시보드는 정상 동작(경고만 출력)하도록 방어 처리됨
  - ⚠️ 이력 테이블 RLS는 select/insert/update만 허용(delete 정책 없음) — 행 삭제는 Supabase SQL Editor에서만 가능(RLS 우회)

## 한국 종목 지원 (v3.1~, 진행 중)
- 🚧 1단계(시세+신호): 코드 완료, **배포 대기**
  - 시세: `FinanceDataReader`(무료·무키, 네이버/KRX) — 브라우저 버튼 불가, 매일 Actions로만 수집
  - 신규 파일: `scripts/update_prices_kr.py`, `.github/workflows/update-prices-kr.yml`(평일 16:30 KST)
  - index.html v3.1: 6자리 숫자 티커=한국주식 자동인식, 원화(₩) 표시(px 헬퍼), "시세 업데이트" 버튼은 한국 종목 건너뜀
  - 4종목 + 시세(각 199일치)는 이미 Supabase에 적재 완료 → index.html 배포하면 화면에 뜸
  - 새 시크릿 불필요(FinanceDataReader 무키, 기존 SUPABASE 시크릿만 사용)
- 🚧 2단계(진단점수): 코드 완료, **배포 대기** (점수는 이미 DB에 적재되어 대시보드에 표시됨)
  - DART fnlttSinglAcntAll(사업보고서 전체 재무제표)로 채점, 미국과 동일한 100점 밴드
  - 신규 파일: `scripts/update_scores_kr.py`, `.github/workflows/update-scores-kr.yml`(월 08:00 KST)
  - 신규 시크릿 `DART_API_KEY` 등록 필요 (자동화용)
  - 현재 점수: SK하이닉스 93 · 삼성전자 71 · HPSP 70 · 대한전선 33 (2026-07-04, 이력도 적재됨)
  - 파싱 주의: 손익계정이 회사따라 IS/CIS 혼재, 계정명 공백/(손실) 변형 → 정규화+부분일치로 대응
  - 한계: DART 연간 사업보고서 기준(TTM 아님), 발행주식수는 당기순이익/EPS 근사(P/FCF용)
  - ⚠️ Twelve Data 무료=한국시세 불가, Finnhub 무료=한국재무 불가 (테스트로 확인됨)

## 신호 전환 알림 (텔레그램, 진행 중)
- 🚧 코드 완료, **배포 대기**
  - 신규 파일: `signal_state_setup.sql`(새 테이블 momentum_signal_state), `scripts/notify_signals.py`, `.github/workflows/check-signals.yml`
  - 매일 2회 체크(08:00·22:30 UTC = 한국·미국 장마감 후) 신호 재계산 → 직전과 다른 종목만 텔레그램 알림
  - 신호 로직은 index.html computeStock() 파이썬 이식(정배열+기준선 이탈 매도+눌림목)
  - 첫 실행은 조용히 상태 저장 + '알림 켜짐' 확인 메시지만
  - 신규 시크릿 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`(=6127932684) 등록 필요
  - 봇: @jason_momentum_bot ("모멘텀 알림")

## 다중 사용자(소유자별 종목) — v3.2, 진행 중
- 🚧 코드 완료, **배포 대기** (owner 마이그레이션 SQL은 실행 완료됨)
  - 방식: 로그인 없이 URL `?u=<owner>`로 사람별 종목 분리 (신뢰하는 지인 2~5명용)
  - `momentum_stocks`에 `owner` 컬럼 + PK를 `(owner,ticker)`로 변경 (`owner_setup.sql`, 실행됨 → 기존 10종목=jason)
  - **시세·점수·이력은 종목(티커) 기준 공유** — 여러 소유자가 같은 종목 담아도 자동수집은 고유 티커만(dedup) → 무료 API 절약
  - index.html v3.2: `?u=` 필터 + 헤더 소유자 드롭다운, 종목 추가/삭제 owner 스코프
  - index.html v3.3: 눌림목(pull) 카드에 "📍 매수 타이밍" 가이드(지지선/반등 후 진입/손절선=기준선, 시장위험시 잠금 안내) 추가 — `buyTip()`
  - 자동화 5개 스크립트: 고유 티커만 수집하도록 dedup 적용(update_prices/-kr, update_scores/-kr, notify_signals)
  - ⚠️ 한계: 로그인 없음 → URL만 알면 남의 리스트 조회/수정 가능(지인 신뢰 전제). 진짜 격리는 Supabase Auth 필요(미구현)
  - 미구현: 친구별 텔레그램 알림(현재 Jason 1인만), 클라이언트 API 키 제거(공유 시 키 노출 상태)

## DRAM 사이클 모니터 — v3.4, 진행 중
- 🚧 코드 완료, **배포 대기**
  - 신규 파일: `dram_setup.sql`(새 테이블 dram_prices), index.html v3.4에 "DRAM 사이클 모니터" 섹션
  - 관리자(owner=jason)만 보이는 입력폼으로 스팟·계약가격 수동 입력(주/월 1회) → 추세 차트 + 자동 신호
  - 신호: 스팟>계약=🟢정상 / 근접(≤3%)=🟡주의 / 스팟<계약=🔴사이클 종료 경고
  - 추적 제품: DDR4 8Gb(단일, DRAM_PRODUCT 상수). 데이터 출처는 TrendForce 공개 스팟 + 월간 계약 뉴스
  - ⚠️ DRAM 가격은 무료 자동 API 없음(TrendForce/DRAMeXchange 유료, 계약가는 Gold+ 전용) → 수동 입력이 기본. 느린 매크로 신호라 주/월 1회로 충분
  - dram_prices 테이블 없어도 대시보드 정상 동작(경고만)

## 3상태 분류 레이어 (BUY/WATCH/EXIT_IMMINENT) — v3.5, 진행 중
- 사양: `momentum-v2/HANDOFF_momentum_classifier.md` (미주은 방법론 규칙화, 의사결정 보조 플래그)
- 🚧 코드·검증 완료, **GitHub 업로드 대기** (SQL은 실행됨, 백필도 완료)
  - 신규: `classification_setup.sql`(새 테이블 momentum_classification), `scripts/classify.py`, `scripts/test_classify.py`, `.github/workflows/classify.yml`(08:00·22:30 UTC)
  - index.html v3.5: 카드에 상태 배지 + 청산선거리 + 근거 툴팁 + 상태필터 + 청산임박 우선정렬
  - 단위테스트 17/17 통과(스펙 7절 7케이스), 백필 11/11 성공 → BUY 0 · WATCH 4 · EXIT 7
  - 워크플로가 classify.py 실행 전에 test_classify.py를 먼저 돌림(로직 깨지면 저장 안 되게)
- 스펙 대비 적응(0절 "실제 우선" 지시에 따름):
  - momentum_stocks가 (owner,ticker)라 분류는 **별도 테이블(ticker 기준)** — 중복 티커 1회만 계산
  - SMA200 미사용(2.2 로직이 20/50만 씀 + US는 148일뿐이라 불가)
  - valuation: forward EPS/멀티플 근거 없음 → 스펙 3절 폴백(통과 + reason 명시). `forwardPE`는 Finnhub 무료로 있으나 assumed_multiple 근거가 없어 순환논리(스펙 144줄 경고) → 미사용
  - is_cyclical = 000660·005930·MU·SNDK·WDC·403870(HPSP)
- ⚠️ **미해결 결정사항 — BUY 게이트가 사실상 작동 불가**
  - 진단점수는 연간/TTM 재무 기반이라 **주간 재계산해도 값이 안 변함**(AMD 71×5회, MU 89×5회 확인)
  - → earnings_momentum이 항상 FLAT → BUY(=UP 요구)가 영원히 안 뜸. 백필 결과 BUY 0.
  - 검토한 선택지: ①점수 '수준' 사용(예: score>=70 AND not DOWN, CONFIG 튜닝) ②FLAT 허용(DOWN만 배제) ③Finnhub `recommendation`(무료·US만) 도입 ④그대로 두기
  - Jason 결정 대기 중 (미결정 상태로 두면 BUY는 분기 실적 갱신 때만 가능)
- 참고: `dist_to_exit_pct`는 이탈 확정 종목에선 값이 커서(전저점까지 거리) 오해 소지 → UI는 exit_triggered=true면 "이탈 확정"으로 표시하도록 처리함

## 가격 레벨(ATR) + 상대강도(RS) — v3.6, 진행 중
- 배경: "매매 신호 근거·타이밍이 단조롭다" → 외부 컨설팅안(DB증권API+4팩터+Claude근거)을 검토했으나 축소 채택
  - DB증권 API 안 씀: 한국전용(US 7종목 커버X)+계좌/OAuth+Actions 부적합 → **KR 수급은 나중에 pykrx(무료)로**
  - 뉴스톤/Claude 근거생성 보류: 노이즈+미지의 뉴스API+환각/비용. classify.py의 결정적 reasons로 충분
  - 채택: ①ATR 가격레벨 ②상대강도(RS) — 둘 다 무료 데이터
- 🚧 코드·계산검증 완료, **SQL 실행 + 업로드 대기**
  - 신규: `signals_levels_setup.sql`(momentum_classification에 컬럼 9개 추가), classify.py에 ATR/RS 로직
  - 가격레벨: 손절=현재가-ATR×1.8(지지선 반영), **목표=실제 저항선(전고점)** → R:R이 종목마다 달라짐(원안의 고정 2.5 개선). 이탈확정 종목은 목표/RR 비적용(오해 방지)
  - RS: 벤치마크 대비 60일 초과수익(%p). 매핑 US반도체→SOXX, US기타→SPY, KR→KS11, KOSDAQ(403870)→KQ11
  - **벤치마크 시세는 momentum_prices에 종목처럼 적재**(SPY·SOXX·KS11·KQ11, 이미 seed 완료) — momentum_stocks엔 없어서 카드로 안 뜸
  - ⚠️ 가격 스크립트(update_prices/-kr)에 벤치마크 티커를 추가해야 매일 갱신됨(아직 미반영 — 업로드 시 반영 필요)
  - index.html v3.6: 카드에 손절/목표/R:R + RS 요약줄. 새 컬럼 없어도 방어(안 깨짐)
  - 단위테스트 17/17 유지
- v3.8 추가: **추세 구조(되돌림/저점구조) + 매물대 + 코스피/코스닥 시장 패널** (이호석 유튜브 방법론 반영)
  - `trend_structure_setup.sql`(컬럼 7개: retrace_pct, swing_peak/trough, trend_structure, vp_poc/resistance/support)
  - classify.py: retracement_frame(고점→저점 회복%), trend_structure(저점 반으로 나눠 상승/하락/횡보), volume_profile(가격버킷 거래량 밀집=매물벽)
  - **KS11/KQ11도 classify에 태움**(MARKET_INDICES) → 시장 패널이 momentum_classification에서 읽음(별도 테이블·JS로직 중복 없음)
  - 목표가는 전고점 유지(R:R 의미), **매물벽(vp_resistance)은 '1차 저항' 정보로 분리** — 매물벽을 목표로 쓰면 R:R이 무의미하게 낮아지는 문제 발견해서 분리
  - index.html v3.8: 카드에 되돌림/구조/1차저항 줄, 시장 추세 패널(되돌림 바+구조 배지+해석)
- v3.7 추가: **RS 추이(개선/악화)** + **상태×RS 해석 가이드(접이식 표)**
  - `rs_trend_setup.sql`(컬럼 2개: rs_trend, rs_trend_label 추가)
  - classify.py: rs_at(offset)로 현재 RS − 20거래일 전 RS = 추이(%p), ±2%p 밴드로 개선/유지/악화
  - index.html: RS 옆에 ↑개선/↓악화 화살표, 필터바 아래 해석 가이드 `<details>` 표
  - loadClassification을 `select('*')`로 변경 → 새 컬럼 없어도 조회 안 깨짐(배포 순서 의존 제거)

## ⚠️ 배포(호스팅) 이슈 — Netlify 크레딧 소진
- momentum-db.netlify.app이 팀("화장품마케팅영어") 크레딧 소진으로 **production deploy가 Skipped** → 라이브가 옛 v1.1에 멈춤
- GitHub엔 v3.1까지 반영됨(코드/데이터/Actions 자동화는 모두 정상, 화면만 안 바뀜)
- 해결 방향: **Cloudflare Pages로 이전**(Jason이 타 프로젝트도 CF 사용 중). 빌드명령 없음, 출력 디렉터리 `/`
- 이후 GitHub push하면 CF 자동배포 → v3.2~v3.4가 한꺼번에 라이브

## v3 후보 (다음 작업)
- ✅ 진단점수 이력 저장 및 변화 추적 — 완료 (추세 차트 포함)
- ✅ 알림 기능 (신호 전환 시) — 텔레그램, 배포 완료
- ✅ 종목 추가/삭제 UI — 종목 관리 섹션에 존재(소유자별로 동작)
- 종목별 가격/점수 추세 차트 — 점수 추세는 완료, 가격 추세는 상세 차트로 기존 제공

## 작업 규칙
1. 기존에 작동하는 기능을 깨뜨리지 않는다 (특히 Actions 워크플로우, Supabase 스키마)
2. 수정 후 커밋 메시지는 한국어로 간결하게
3. index.html 수정 시 버전 마커 갱신
4. 시크릿/API 키를 코드에 하드코딩하지 않는다 (index.html의 Supabase anon key는 예외 — 공개용 키)
5. 큰 변경 전에 Jason에게 계획을 먼저 설명하고 확인받는다
