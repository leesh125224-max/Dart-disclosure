# 📢 DART 실시간 공시 모니터링 & AI 요약 파이프라인

금융감독원 **DART(전자공시시스템) RSS**를 실시간 감지하여, 핵심 공시를 **규칙 기반 정밀 파서** 및 **Gemini AI**로 자동 요약한 뒤 **텔레그램 알림 발송** 및 **Supabase DB 적재**를 수행하는 자동화 파이프라인입니다.

---

## 🌟 주요 기능

1. **실시간 공시 감지 & 시가총액 매핑**
   - DART 공식 RSS 피드를 통해 공시 등록 즉시 감지 (운영시간: 평일 07:30 ~ 19:00).
   - 네이버 증권 연동으로 기업 시가총액 자동 조회 및 표기.
2. **지능형 공시 요약 엔진 (하이브리드)**
   - **수치/계약형 공시:** 단일판매·공급계약, 유상/무상증자, 전환사채, 감자, 주식소각, 자기주식, 유형자산 취득/처분, 대량보유 등 전용 파서로 핵심 수치·일정 추출.
   - **정기보고서 (반기/분기/사업):** `요약재무정보`에서 매출액, 영업익, 순이익 및 증감률 추출.
   - **[기재정정] 공시:** 상단 정정 전·후 비교표(정정사유 포함) + 하단 상세 본문 요약 결합.
   - **비정형/판단형 공시:** 소송, 합병, 투자판단관련, 기타주요경영사항 등은 **Gemini AI** (`3.8 2회` ➔ `3.7` ➔ `3.6` ➔ `3.5` 폴백 + Google Search Grounding)로 3줄 핵심 요약.
3. **텔레그램 발송 & Supabase 중복 차단**
   - 텔레그램 알림 발송에 최종 성공한 건만 Supabase DB에 저장하여 중복 발송 완전 방지.

---

## 🔑 환경 변수 (`.env`)

| 환경 변수명 | 설명 |
| :--- | :--- |
| `DART_API_KEY` | OpenDART 인증키 |
| `GEMINI_API_KEY` | Google Gemini API 키 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 수신 Chat ID |
| `SUPABASE_URL` | Supabase 프로젝트 URL (`https://xxx.supabase.co`) |
| `SUPABASE_KEY` | Supabase `service_role` 비밀 키 |

---

## 🗄️ Supabase 테이블 DDL

Supabase SQL Editor에서 실행:

```sql
create table dart_announcements (
    id bigint generated always as identity primary key,
    rcept_no varchar(20) not null unique,        -- DART 접수번호 (중복 방지)
    corp_name varchar(100) not null,            -- 회사명
    report_name text not null,                   -- 공시 제목
    stock_code varchar(10),                      -- 종목코드
    rcept_dt date not null,                      -- 접수일자 (YYYY-MM-DD)
    ann_time timestamp with time zone not null,  -- 공시 등록 시간 (KST)
    summary_json jsonb,                          -- 요약 내용 JSON
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

create index idx_dart_ann_rcept_dt on dart_announcements(rcept_dt);
```

---

## 🚀 실행 방법

1. **패키지 설치**
   ```bash
   pip install -r requirements.txt
   ```
2. **실행**
   - **실시간 모니터링 실행:**
     ```bash
     python execution/main.py
     ```
   - **공시 유형별 요약 추출 검증 (테스트):**
     ```bash
     python execution/json_test.py
     ```
