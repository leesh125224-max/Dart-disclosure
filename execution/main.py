import sys
import datetime
import requests
import xml.etree.ElementTree as ET
import urllib.parse
import email.utils
from pathlib import Path
from bs4 import BeautifulSoup

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).resolve().parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from config import settings
from core.dart import DartClient
from core.telegram import TelegramClient
from core.supabase_client import SupabaseClient
from core.gemini_client import GeminiClient

import os

# ──────────────────────────────────────────────────────────────
# [설정]
# ──────────────────────────────────────────────────────────────
SAVE_RAW_HTML  = os.getenv("SAVE_RAW_HTML", "False").lower() in ("true", "1")  # 로컬 디버깅 시에만 True로 켬
HTML_SAVE_DIR  = project_root / "scratch" / "html_samples"
# ──────────────────────────────────────────────────────────────

def run_pipeline():
    print("=" * 60)
    print("📢 DART 실시간 공시 수집 및 Supabase/텔레그램 연동 파이프라인 시작")
    print("=" * 60)

    # 1. 설정값 검증
    if not settings.validate_config():
        return

    # 2. 클라이언트 초기화
    try:
        client = DartClient(settings.DART_API_KEY)
        telegram_client = TelegramClient(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_CHAT_ID)
        supabase_client = SupabaseClient(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        gemini_client = GeminiClient(settings.GEMINI_API_KEY)
    except Exception as e:
        print(f"❌ 클라이언트 초기화 실패: {type(e).__name__}")
        return

    # 한국 표준시 (KST, UTC+9) 설정 (GitHub Actions 서버 타임존 UTC 대응)
    kst = datetime.timezone(datetime.timedelta(hours=9))
    now_kst = datetime.datetime.now(kst)
    today_str = now_kst.strftime("%Y-%m-%d")
    today_str_nodash = today_str.replace("-", "")

    # 3. DART RSS로부터 실시간 공시 목록 수집
    rss_url = "https://dart.fss.or.kr/api/todayRSS.xml"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        print(f"🔍 DART RSS 피드를 수집하는 중... (URL: {rss_url})")
        response = requests.get(rss_url, headers=headers, timeout=15)
        response.raise_for_status()
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
    except Exception as e:
        print(f"❌ DART RSS 수집 실패: {type(e).__name__}")
        return

    if not items:
        print(f"ℹ️ DART RSS에 조회된 오늘 공시 항목이 없습니다. (날짜: {today_str})")
        return

    # 4. RSS 아이템 파싱 및 정상화
    rss_announcements = []
    for item in items:
        title = item.find("title").text if item.find("title") is not None else ""
        link = item.find("link").text if item.find("link") is not None else ""
        pub_date_str = item.find("pubDate").text if item.find("pubDate") is not None else ""
        
        # 접수번호(rcpNo) 추출
        rcept_no = ""
        if link:
            parsed_url = urllib.parse.urlparse(link)
            params = urllib.parse.parse_qs(parsed_url.query)
            if "rcpNo" in params:
                rcept_no = params["rcpNo"][0]
        
        if not rcept_no:
            continue

        # 시간 파싱 (GMT -> KST 한국시간 변환)
        ann_time_str = ""
        rcept_dt = today_str
        if pub_date_str:
            try:
                dt_utc = email.utils.parsedate_to_datetime(pub_date_str)
                dt_kst = dt_utc + datetime.timedelta(hours=9)
                ann_time_str = dt_kst.strftime("%Y-%m-%d %H:%M")
                rcept_dt = dt_kst.strftime("%Y-%m-%d")
            except Exception as e:
                print(f"⚠️ 시간 파싱 오류 ({pub_date_str}): {type(e).__name__}")
                ann_time_str = f"{now_kst.strftime('%Y-%m-%d %H:%M')} (rss 시간 매칭 실패)"
        else:
            ann_time_str = f"{now_kst.strftime('%Y-%m-%d %H:%M')} (rss 시간 매칭 실패)"

        # 회사명 및 보고서명 분리
        corp_name = "알수없음"
        report_nm = title
        import re
        # 패턴 1: (시장구분)회사명 - 보고서명 (예: (코스닥)엔젯 - 단일판매ㆍ공급계약체결)
        m1 = re.match(r"^\((유가|코스닥|코넥스|기타)\)\s*(.*?)\s*-\s*(.*)$", title)
        market_type = ""
        if m1:
            market_type = m1.group(1).strip()
            corp_name = m1.group(2).strip()
            report_nm = m1.group(3).strip()
        else:
            # 패턴 2: [회사명] 보고서명 (예: [삼성전자] 유상증자결정)
            m2 = re.match(r"^\[(.*?)\]\s*(.*)$", title)
            if m2 and m2.group(1).strip():
                corp_name = m2.group(1).strip()
                report_nm = m2.group(2).strip()

        # 유가증권(유가) 및 코스닥 공시만 유지 (기타/코넥스/미상장 제외)
        if market_type and market_type not in ("유가", "코스닥"):
            continue

        rss_announcements.append({
            "corp_name": corp_name,
            "report_nm": report_nm,
            "rcept_no": rcept_no,
            "rcept_dt": rcept_dt,
            "ann_time": ann_time_str,
            "stock_code": "",
            "corp_code": ""
        })

    # 5. Supabase DB에서 오늘 이미 처리 완료된 접수번호 목록 가져오기
    processed_rcept_nos = supabase_client.get_today_processed_rcept_nos(today_str)
    print(f"📊 Supabase DB에 기록된 오늘 처리 완료 건수: {len(processed_rcept_nos)}건")

    # DB에 존재하지 않는 새로운 공시만 필터링 (중복 방지)
    new_announcements = [ann for ann in rss_announcements if ann["rcept_no"] not in processed_rcept_nos]

    # 6. DART Open API를 통해 신규 공시들의 stock_code 및 corp_code 매칭하여 보완 및 RSS 누락분 추가
    try:
        api_announcements = client.get_today_announcements(today_str_nodash)
        if api_announcements:
            api_map = {item.get("rcept_no"): item for item in api_announcements if item.get("rcept_no")}
            rss_rcept_nos = {ann["rcept_no"] for ann in new_announcements}

            valid_new = []
            for ann in new_announcements:
                rno = ann["rcept_no"]
                if rno in api_map:
                    item_info = api_map[rno]
                    corp_cls = item_info.get("corp_cls", "")
                    # Y: 유가증권(KOSPI), K: 코스닥만 유지 (N: 코넥스, E: 기타 제외)
                    if corp_cls and corp_cls not in ("Y", "K"):
                        continue
                    ann["stock_code"] = item_info.get("stock_code") or ""
                    ann["corp_code"] = item_info.get("corp_code") or ""
                    if item_info.get("corp_name"):
                        ann["corp_name"] = item_info.get("corp_name")
                    if item_info.get("report_nm"):
                        ann["report_nm"] = item_info.get("report_nm")
                valid_new.append(ann)

            # RSS 피드가 밀려서 누락되었으나 OpenDART API에 존재하는 공시 추가
            for rno, api_item in api_map.items():
                if rno not in processed_rcept_nos and rno not in rss_rcept_nos:
                    corp_cls = api_item.get("corp_cls", "")
                    if corp_cls in ("Y", "K"):
                        rdt = api_item.get("rcept_dt", today_str_nodash)
                        rdt_fmt = f"{rdt[:4]}-{rdt[4:6]}-{rdt[6:]}" if len(rdt) == 8 else today_str
                        valid_new.append({
                            "corp_name": api_item.get("corp_name", "알수없음"),
                            "report_nm": api_item.get("report_nm", ""),
                            "rcept_no": rno,
                            "rcept_dt": rdt_fmt,
                            "ann_time": f"{now_kst.strftime('%Y-%m-%d %H:%M')} (rss 시간 매칭 실패)",
                            "stock_code": api_item.get("stock_code") or "",
                            "corp_code": api_item.get("corp_code") or ""
                        })

            new_announcements = valid_new
    except Exception as e:
        print(f"⚠️ DART API 상세 메타데이터 매칭 중 오류 발생: {type(e).__name__} (기본값으로 진행)")

    if not new_announcements:
        print("ℹ️ 새로 업데이트된 공시가 없습니다.")
        return

    print(f"🔍 중복 제거 후 새로 수집된 공시 건수: {len(new_announcements)}건")

    # 7. 핵심 공시 필터링
    critical = client.filter_critical_announcements(new_announcements)
    if not critical:
        print("ℹ️ 필터 조건에 부합하는 핵심 공시가 없습니다.")
        return

    print(f"🎯 {len(critical)}건의 신규 핵심 공시 검출 완료!\n")

    # 8. 공시별 처리 루프
    save_dir = HTML_SAVE_DIR if SAVE_RAW_HTML else None

    # 오래된 공시부터 전송하고 DB에 쌓기 위해 시간 순서대로 정렬 (역순 배치)
    critical.reverse()

    for i, ann in enumerate(critical, 1):
        corp_name   = ann.get("corp_name", "-")
        report_name = ann.get("report_nm", "-")
        rcept_no    = ann.get("rcept_no", "-")
        stock_code  = ann.get("stock_code", "")
        rcept_dt    = ann.get("rcept_dt", "-")
        ann_time    = ann.get("ann_time", "")

        print(f"{'─' * 60}")
        print(f"📂 [{i}/{len(critical)}] {corp_name} ({stock_code or '미상장'}) | {report_name}")
        print(f"   접수번호: {rcept_no} | 시간: {ann_time}")

        # 핵심 분기 판단: 오직 '투자판단관련 주요경영사항'만 Gemini 요약 대상으로 판정
        name_clean = report_name.replace(" ", "")
        is_major_event = ("투자판단" in name_clean and "주요경영사항" in name_clean) or "투자판단관련" in name_clean

        summary_content = ""
        summary_data = {}

        if is_major_event:
            print("🤖 [Gemini 요약 대상] 주요경영사항 본문을 다운로드하여 Gemini로 요약합니다...")
            # DART API로부터 HTML 원본 다운로드
            raw_html = client._download_zip_html(rcept_no)
            if raw_html.startswith("❌"):
                summary_content = f"⚠️ 공시 본문 다운로드 실패로 요약을 수행하지 못했습니다.\n원문 링크를 참고해 주세요."
            else:
                # HTML 텍스트 파싱하여 태그 제거 후 텍스트만 추출
                soup = BeautifulSoup(raw_html, "html.parser")
                plain_text = soup.get_text("\n", strip=True)
                # Gemini 호출
                summary_content = gemini_client.summarize_disclosure(corp_name, report_name, plain_text)
            
            summary_data = {
                "type": "gemini_summary",
                "content": summary_content
            }
        else:
            print("⚙️ [규칙 기반 요약 대상] 파이썬 로컬 파서로 핵심 요약을 수행합니다...")
            # 기존 규칙 기반 요약 및 파싱 함수 실행
            summary_content = client.get_announcement_content(ann, save_html_dir=save_dir)
            
            summary_data = {
                "type": "rule_based_summary",
                "content": summary_content
            }

        # 텔레그램 메시지 포맷 구성
        dart_link = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
        tg_message = (
            f"보고서명: {report_name}\n"
            f"회사명: {corp_name} ({stock_code or '미상장'})\n"
            f"공시시간 : {ann_time}\n\n"
            f"{summary_content}\n\n"
            f"공시링크: <a href=\"{dart_link}\">DART에서 보기</a>"
        )

        # 텔레그램 전송
        print(f"📤 [{i}/{len(critical)}] 텔레그램 발송 중...")
        successes = telegram_client.send_large_message(tg_message)
        
        if all(successes):
            print("✅ 텔레그램 발송 완료")
            
            # 발송 성공 시에만 Supabase DB에 기록하여 재시도 가능 보장
            db_data = {
                "rcept_no": rcept_no,
                "corp_name": corp_name,
                "report_name": report_name,
                "stock_code": stock_code or None,
                "rcept_dt": rcept_dt,
                "ann_time": ann_time,
                "summary_json": summary_data
            }
            supabase_client.insert_announcement(db_data)
        else:
            print("❌ 일부 텔레그램 메시지 발송 실패 (Supabase 저장 보류)")

    print(f"\n{'=' * 60}")
    print(f"🎉 파이프라인 완료! 총 {len(critical)}건 처리 완료")

if __name__ == "__main__":
    run_pipeline()
