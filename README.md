# 📢 DART 실시간 공시 알림 & Supabase 연동 파이프라인

금융감독원 **DART(전자공시시스템) RSS 및 API**를 활용하여 실시간으로 주요 공시를 감지하고, **Gemini AI** 및 자체 규칙 기반 엔진으로 핵심 내용을 요약하여 **텔레그램 알림 발송** 및 **Supabase DB 적재**를 수행하는 파이프라인입니다.

---

## 🌟 주요 기능

1. **실시간 공시 감지 (DART RSS)**
   - `todayRSS.xml`을 활용하여 공시가 등록된 **정확한 시각(시:분:초)**과 접수번호(`rcept_no`)를 초단위로 추출합니다.
2. **중복 발송 완전 차단 (Supabase DB)**
   - 공시 처리 전 Supabase DB에서 오늘 이미 전송된 접수번호 목록을 조회하여 중복 발송을 차단합니다.
   - 텔레그램 발송에 **최종 성공한 공시만 DB에 적재**하여 네트워크 실패 시에도 다음 주기에 안전하게 재시도됩니다.
3. **지능형 공시 요약 분기**
   - **일반 핵심 공시(유상증자, 감자, 전환사채 등):** 파이썬 규칙 기반(Rule-based) 파서로 빠르게 핵심 수치를 추출합니다.
   - **투자판단관련 주요경영사항:** 본문 HTML 텍스트를 BeautifulSoup으로 추출 후 **Google Gemini API**로 실시간 요약본을 작성합니다.
4. **텔레그램 실시간 알림**
   - 공시 제목, 회사명(종목코드), DART 원본 링크, 요약 내용, 공시 등록 시각(`YYYY-MM-DD HH:MM:SS`)을 텔레그램 채널/개인 챗으로 즉시 전송합니다.
5. **무료 24시간 무중단 자동화 (GitHub Actions)**
   - 평일 주식시장 운영 시간대에 맞춰 5분 주기로 자동으로 구동되며, 추가 서버 비용 없이 구동됩니다.

---

## 🛠️ 기술 스택

- **Language:** Python 3.11
- **API & Data Source:** OpenDART API, DART RSS, Google Gemini API, Telegram Bot API
- **Database:** Supabase (PostgreSQL)
- **CI/CD & Automation:** GitHub Actions

---

## 📂 프로젝트 구조

```text
📁 Dart 공시
 ├── 📁 .github/workflows
 │    └── 📄 dart_pipeline.yml     # GitHub Actions 15분 주기 자동화 스케줄러
 ├── 📁 config
 │    └── 📄 settings.py                 # 환경변수 로드 및 설정 유효성 검증
 ├── 📁 core
 │    ├── 📄 dart.py                     # DART API 연동 및 규칙 기반 공시 파서
 │    ├── 📄 telegram.py                 # 텔레그램 메시지 발송 모듈
 │    ├── 📄 supabase_client.py          # Supabase DB 이력 조회 및 저장 모듈
 │    └── 📄 gemini_client.py            # 보안이 강화된 Gemini API 공시 요약 모듈
 ├── 📁 execution
 │    └── 📄 main.py                     # 파이프라인 메인 실행 스크립트
 ├── 📄 .gitignore                       # API 키 및 비밀 환경변수 포함 차단 파일
 ├── 📄 requirements.txt                 # 의존성 라이브러리 목록
 └── 📄 README.md                        # 프로젝트 안내 문서
```

---

## 🔑 환경 변수 (Environment Variables)

로컬 실행 시 `.env` 파일에, GitHub Actions 이용 시 **Repository Secrets**에 등록해야 하는 환경 변수 항목입니다.

| 환경 변수명 | 설명 |
| :--- | :--- |
| `DART_API_KEY` | OpenDART 인증키 |
| `GEMINI_API_KEY` | Google Gemini API 키 |
| `TELEGRAM_BOT_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 수신 채널/사용자 Chat ID |
| `SUPABASE_URL` | Supabase 프로젝트 URL (`https://xxx.supabase.co`) |
| `SUPABASE_KEY` | Supabase `service_role` 마스터 비밀 키 |

---

## 🗄️ Supabase 테이블 설정 (DDL)

Supabase SQL Editor에서 아래 쿼리를 실행하여 테이블 및 인덱스를 미리 생성해 주세요.

```sql
create table dart_announcements (
    id bigint generated always as identity primary key,
    rcept_no varchar(20) not null unique,        -- DART 접수번호 (유니크)
    corp_name varchar(100) not null,            -- 회사명
    report_name text not null,                   -- 공시 제목
    stock_code varchar(10),                      -- 종목코드
    rcept_dt date not null,                      -- 접수일자 (YYYY-MM-DD)
    ann_time timestamp with time zone not null,  -- 공시 등록 정확한 시간 (KST 기준)
    summary_json jsonb,                          -- 파싱 결과 / Gemini 요약본 JSON
    created_at timestamp with time zone default timezone('utc'::text, now()) not null
);

-- 오늘 날짜 조회를 위한 인덱스 생성
create index idx_dart_ann_rcept_dt on dart_announcements(rcept_dt);
```

---

## 🚀 로컬 실행 방법

1. **의존성 라이브러리 설치**
   ```bash
   pip install -r requirements.txt
   ```
2. **`.env` 파일 생성 후 환경 변수 입력**
3. **파이프라인 실행**
   ```bash
   python execution/main.py
   ```
