import requests
import io
import zipfile
import re
import datetime
import warnings
from pathlib import Path
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional

# XML을 HTML 파서로 읽을 때 발생하는 BeautifulSoup 경고 무시
warnings.filterwarnings("ignore", message=".*parsing an XML document using an HTML parser.*")


class DartClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("DART API Key가 설정되지 않았습니다.")
        self.api_key = api_key

        # OpenDART API 기본 Endpoint
        self.list_url = "https://opendart.fss.or.kr/api/list.json"
        self.doc_url  = "https://opendart.fss.or.kr/api/document.xml"

        # ──────────────────────────────────────────────────────────────
        # 필터링 대상 공시명 (공시 목록.txt 기반 / 실제 DART 공시명 부분 문자열)
        # ──────────────────────────────────────────────────────────────
        self.target_report_names = [
            # 정기공시
            "사업보고서", "반기보고서", "분기보고서",

            # 주요사항보고서
            "유상증자결정", "무상증자결정", "감자결정",
            "전환사채권발행결정", "신주인수권부사채권발행결정", "교환사채권발행결정",
            "회사합병결정", "회사분할결정", "주식교환·이전결정",
            "영업양수결정", "자기주식취득결정", "자기주식처분결정", "주식소각결정",
            "채권은행등의관리절차개시", "부도발생", "해산사유발생",
            "영업정지", "회생절차개시신청", "파산신청",

            # 수시공시
            "매출액또는손익구조", "타법인주식및출자증권취득결정",
            "유형자산취득결정", "유형자산처분결정",
            "특허권등지식재산권취득결정", "소송등의제기·신청",

            # 계약 공시
            "단일판매·공급계약",   # U+00B7 가운뎃점
            "단일판매ㆍ공급계약",   # U+318D 한글 아래아점 (DART 실제 사용 문자)

            # 수시공시 (추가)
            "중대재해",
        ]

        # ──────────────────────────────────────────────────────────────
        # 주요사항보고서 JSON API 매핑
        # ──────────────────────────────────────────────────────────────
        self.event_api_mappings = {
            "부도발생":             "dfOcr",
            "영업정지":             "bsnSp",
            "회생절차":             "ctrcvsBgrq",
            "해산사유":             "dsRsOcr",
            "유상증자결정":         "piicDecsn",
            "무상증자결정":         "fricDecsn",
            "감자결정":             "crDecsn",
            "관리절차개시":         "bnkMngtPcbg",
            "소송":                 "lwstLg",
            "전환사채권발행결정":   "cvbdIsDecsn",
            "신주인수권부사채권발행결정": "bdwtIsDecsn",
            "교환사채권발행결정":   "exbdIsDecsn",
            "타법인증권양도":       "otcprStkInvscrTrfDecsn",
            "유형자산양도":         "tgastTrfDecsn",
            "유형자산양수":         "tgastInhDecsn",
            "타법인증권양수":       "otcprStkInvscrInhDecsn",
            "영업양도":             "bsnTrfDecsn",
            "영업양수":             "bsnInhDecsn",
            "자기주식처분결정":     "tsstkDpDecsn",
            "자기주식취득결정":     "tsstkAqDecsn",
            "주식교환":             "stkExtrDecsn",
            "회사분할합병":         "cmpDvmgDecsn",
            "회사분할결정":         "cmpDvDecsn",
            "회사합병결정":         "cmpMgDecsn",
        }

        # 지분공시 JSON API 매핑
        self.share_api_mappings = {
            "대량보유상황보고":                   "majorstock",
            "임원ㆍ주요주주소유보고":             "elestock",
            "주식등의대량보유상황보고서":         "majorstock",
            "임원ㆍ주요주주특정증권등소유상황보고서": "elestock",
        }

        # 한글 필드명 변환 맵 (JSON→표시용)
        self.FIELD_MAP = {
            "corp_name": "회사명", "stock_code": "종목코드",
            "bsns_year": "사업연도", "sj_nm": "재무제표명",
            "account_nm": "계정명", "thstg_amount": "당기금액",
            "frmtrm_amount": "전기금액", "se": "구분",
            "nm": "이름", "ofcps": "직위",
            "fwdg_fnltt_opinion": "감사의견", "audit_opinion": "감사의견",
        }

    # ══════════════════════════════════════════════════════════════════
    # 공시 목록 수집
    # ══════════════════════════════════════════════════════════════════

    def get_today_announcements(self, date_str: str = None) -> List[Dict[str, Any]]:
        """특정 날짜의 전체 공시 목록을 페이지네이션으로 전부 수집합니다."""
        if not date_str:
            date_str = datetime.date.today().strftime("%Y%m%d")
        else:
            date_str = date_str.replace("-", "")

        print(f"🔍 DART 공시 목록 조회 중... (날짜: {date_str})")

        all_list, page_no = [], 1
        while True:
            params = {
                "crtfc_key": self.api_key,
                "bgn_de": date_str, "end_de": date_str,
                "page_no": page_no, "page_count": 100,
            }
            try:
                res = requests.get(self.list_url, params=params, timeout=10).json()
                status = res.get("status")
                if status == "000":
                    curr = res.get("list", [])
                    all_list.extend(curr)
                    if len(curr) < 100:
                        break
                    page_no += 1
                elif status == "013":
                    print(f"ℹ️ {date_str}에 공시된 데이터가 없습니다.")
                    break
                else:
                    print(f"❌ DART API 오류: {res.get('message')} (코드: {status})")
                    break
            except Exception as e:
                print(f"❌ 공시 목록 조회 예외: {type(e).__name__}")
                break

        return all_list

    def filter_critical_announcements(self, announcements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """target_report_names 기반으로 핵심 공시를 필터링합니다."""
        result = []
        for ann in announcements:
            report_name = ann.get("report_nm", "")
            name_clean = report_name.replace(" ", "")

            # [첨부정정]은 무조건 제외
            if "[첨부정정]" in name_clean:
                continue

            # 투자판단관련 주요경영사항 제외
            if "투자판단관련" in name_clean:
                continue

            # [기재정정] 중 특정 유형 제외
            if "[기재정정]" in name_clean:
                if "유상증자결정" in name_clean:
                    continue
                if "회사합병결정" in name_clean:
                    continue

            if any(keyword in name_clean for keyword in self.target_report_names):
                result.append(ann)

        print(f"📊 총 {len(announcements)}건 중 핵심 공시 {len(result)}건 필터링 완료")
        return result

    # ══════════════════════════════════════════════════════════════════
    # 원본 문서 다운로드
    # ══════════════════════════════════════════════════════════════════

    def _download_zip_html(self, rcept_no: str) -> str:
        """접수번호로 DART zip을 내려받아 HTML/XML 원본 텍스트를 반환합니다. 
        자율공시/공정공시 등 document.xml에 없는 800/900번대 공시는 웹 뷰어에서 폴백 수집합니다.
        """
        params = {"crtfc_key": self.api_key, "rcept_no": rcept_no}

        # 1차 시도: OpenDART API document.xml 다운로드
        try:
            res = requests.get(self.doc_url, params=params, timeout=15)
            if res.status_code == 200 and not (b"<status>" in res.content[:100]):
                try:
                    zf = zipfile.ZipFile(io.BytesIO(res.content))
                    html_parts = []
                    for fname in zf.namelist():
                        if fname.lower().endswith((".html", ".htm", ".xml")):
                            raw = zf.read(fname)
                            text = ""
                            for enc in ("cp949", "utf-8", "euc-kr"):
                                try:
                                    text = raw.decode(enc)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            if not text:
                                text = raw.decode("utf-8", errors="ignore")
                            html_parts.append(text)
                    if html_parts:
                        return "\n".join(html_parts)
                except zipfile.BadZipFile:
                    pass
        except Exception:
            pass

        # 2차 시도 (폴백): OpenDART API에 파일이 없는 자율/공정/자회사/단일판매 공시 등은 DART 공시뷰어에서 HTML 수집
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            main_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"
            main_res = requests.get(main_url, headers=headers, timeout=10)
            if main_res.status_code == 200:
                page_text = self._safe_decode_res(main_res)

                # dcmNo 추출: DART main.do 페이지 내 JavaScript 변수 및 함수 호출부 탐색
                dcm_no = None
                dcm_patterns = [
                    # node1['id'] = "10384752"
                    r"node1\['id'\]\s*=\s*['\"](\d{7,15})['\"]",
                    # viewDoc('rcpNo', 'dcmNo', ...)
                    r"viewDoc\(['\"]?\d{12,}['\"]?\s*,\s*['\"]?(\d{7,15})['\"]?",
                    # JSON {"dcmNo": "..."} 또는 dcmNo: "..."
                    r'["\']?dcmNo["\']?\s*[:=]\s*["\']?(\d{7,15})["\']?',
                    # fn_...('rcpNo', 'dcmNo')
                    r'fn_\w+\(["\']?\d{12,}["\']?\s*,\s*["\']?(\d{7,15})["\']?',
                    # viewer.do?rcpNo=...&dcmNo=...
                    r'viewer\.do\?.*?dcmNo=(\d{7,15})',
                    r'dcm_no=(\d{7,15})',
                ]
                for pat in dcm_patterns:
                    m_dcm = re.search(pat, page_text)
                    if m_dcm:
                        cand = m_dcm.group(1)
                        if cand != rcept_no:
                            dcm_no = cand
                            break

                if dcm_no:
                    viewer_url = (
                        f"https://dart.fss.or.kr/report/viewer.do"
                        f"?rcpNo={rcept_no}&dcmNo={dcm_no}"
                        f"&eleId=&offset=0&length=99999999&dtd=html"
                    )
                    viewer_res = requests.get(viewer_url, headers=headers, timeout=15)
                    viewer_text = self._safe_decode_res(viewer_res)
                    if viewer_res.status_code == 200 and len(viewer_text) > 300:
                        return viewer_text

                # dcmNo 추출 실패 시: href/src에서 viewer.do URL 직접 탐색
                main_soup = BeautifulSoup(page_text, "html.parser")
                for tag_a in main_soup.find_all(["a", "iframe"]):
                    href = tag_a.get("href", "") or tag_a.get("src", "")
                    if href and ("viewer.do" in href or "report/viewer" in href):
                        if not href.startswith("http"):
                            href = "https://dart.fss.or.kr" + href
                        v_res = requests.get(href, headers=headers, timeout=10)
                        v_text = self._safe_decode_res(v_res)
                        if v_res.status_code == 200 and len(v_text) > 300:
                            return v_text
        except Exception:
            pass

        return f"❌ 문서 다운로드 실패 (접수번호: {rcept_no})"

    def _safe_decode_res(self, res: requests.Response) -> str:
        """requests 응답 바이트를 cp949, euc-kr, utf-8 순서로 디코딩하여 한글 깨짐을 방지합니다."""
        for enc in ("cp949", "euc-kr", "utf-8"):
            try:
                return res.content.decode(enc)
            except (UnicodeDecodeError, TypeError):
                continue
        return res.text

    def save_raw_html(self, rcept_no: str, corp_name: str, report_name: str, save_dir: Path) -> Optional[Path]:
        """원본 HTML을 파일로 저장합니다 (파서 개발용 샘플 수집)."""
        html = self._download_zip_html(rcept_no)
        if html.startswith("❌"):
            print(f"   ⚠️ HTML 저장 실패: {html}")
            return None
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", f"{corp_name}_{report_name}_{rcept_no}")
        save_dir.mkdir(parents=True, exist_ok=True)
        path = save_dir / f"{safe_name}.html"
        path.write_text(html, encoding="utf-8")
        print(f"   💾 HTML 저장 완료: {path.name}")
        return path

    # ══════════════════════════════════════════════════════════════════
    # 표(table) 텍스트 추출
    # ══════════════════════════════════════════════════════════════════

    def extract_tables_from_html(self, html: str, max_tables: int = 5) -> str:
        """HTML에서 <table> 데이터를 구조화된 텍스트로 추출합니다.
        max_tables: 최대 추출 표 개수 (기본 5개, 초과분은 생략 안내)
        """
        if not html or html.startswith("❌"):
            return html or "ℹ️ 본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all(["table", "TABLE"])
        if not tables:
            return "ℹ️ 표 데이터 없음"

        total = len(tables)
        parsed = []
        for idx, tbl in enumerate(tables[:max_tables], 1):
            rows = tbl.find_all(["tr", "TR"])
            lines = []
            for row in rows:
                cells = row.find_all(["td", "th", "TD", "TH"])
                texts = [re.sub(r"\s+", " ", c.get_text()).replace("&cr;", "").replace("&cr", "").strip() for c in cells]
                if any(texts):
                    lines.append(" | ".join(texts))
            if lines:
                parsed.append(f"[표 {idx}]\n" + "\n".join(lines))

        result = "\n\n".join(parsed)
        if total > max_tables:
            result += f"\n\n(총 {total}개 표 중 {max_tables}개만 표시)"
        return result

    def extract_kv_from_html(self, html: str, target_keys: List[str]) -> Dict[str, str]:
        """HTML 표에서 키-값 쌍을 추출합니다 (단일판매·공급계약 등 비정형 공시용)."""
        result: Dict[str, str] = {}
        if not html or html.startswith("❌"):
            return result

        soup = BeautifulSoup(html, "html.parser")
        for row in soup.find_all(["tr", "TR"]):
            cells = row.find_all(["td", "th", "TD", "TH"])
            if len(cells) < 2:
                continue
            key_raw = re.sub(r"\s+", "", cells[0].get_text())
            val = re.sub(r"\s+", " ", cells[1].get_text()).strip()
            for tk in target_keys:
                tk_clean = tk.replace(" ", "")
                if tk_clean in key_raw and tk not in result:
                    result[tk] = val
        return result

    # ══════════════════════════════════════════════════════════════════
    # JSON API 호출
    # ══════════════════════════════════════════════════════════════════

    def _call_json_api(self, api_type: str, params: dict) -> List[Dict[str, Any]]:
        """OpenDART JSON API를 호출하여 list를 반환합니다."""
        url = f"https://opendart.fss.or.kr/api/{api_type}.json"
        try:
            res = requests.get(url, params=params, timeout=10).json()
            if res.get("status") == "000":
                return res.get("list", [])
            return []
        except Exception as e:
            print(f"❌ JSON API 호출 예외 ({api_type}): {type(e).__name__}")
            return []

    def detect_json_api_type(self, ann: Dict[str, Any]) -> Optional[tuple]:
        """공시명을 분석해 JSON API 지원 여부와 (category, api_type)을 반환합니다."""
        report_name = ann.get("report_nm", "")
        name_clean = report_name.replace(" ", "")

        # 지분공시
        for key, api in self.share_api_mappings.items():
            if key in name_clean:
                return ("share", api)

        # 주요사항보고서
        for key, api in self.event_api_mappings.items():
            if key in name_clean:
                return ("event", api)

        # 정기보고서
        if any(t in report_name for t in ("사업보고서", "반기보고서", "분기보고서")) \
                and not report_name.endswith("첨부"):
            reprt_code = "11011"
            if "반기보고서" in report_name:
                reprt_code = "11012"
            elif "1분기보고서" in report_name or "분기보고서(1분기)" in report_name:
                reprt_code = "11013"
            elif "3분기보고서" in report_name or "분기보고서(3분기)" in report_name:
                reprt_code = "11014"
            return ("report", reprt_code)

        return None

    def get_event_json_details(self, corp_code: str, rcept_no: str, api_type: str, date_str: str) -> List[Dict]:
        date_str = date_str.replace("-", "")
        # 정정 공시의 최초접수일이나 이사회결정일이 다를 때 조회가 누락되지 않도록
        # 검색 시작일(bgn_de)을 조회 접수일자 기준 1년(365일) 전으로 확장하여 호출합니다.
        try:
            dt = datetime.datetime.strptime(date_str, "%Y%m%d")
            bgn_dt = dt - datetime.timedelta(days=365)
            bgn_de = bgn_dt.strftime("%Y%m%d")
        except Exception:
            bgn_de = date_str

        data = self._call_json_api(api_type, {
            "crtfc_key": self.api_key, "corp_code": corp_code,
            "bgn_de": bgn_de, "end_de": date_str,
        })
        filtered = [d for d in data if d.get("rcept_no") == rcept_no]
        return filtered

    def get_share_json_details(self, corp_code: str, rcept_no: str, api_type: str) -> List[Dict]:
        data = self._call_json_api(api_type, {
            "crtfc_key": self.api_key, "corp_code": corp_code,
        })
        filtered = [d for d in data if d.get("rcept_no") == rcept_no]
        return filtered

    def get_finstate_summary(self, corp_code: str, bsns_year: str, reprt_code: str) -> str:
        """단일회사 주요계정 API → 매출액/영업이익/당기순이익 요약 텍스트."""
        data = self._call_json_api("fnlttSinglAcnt", {
            "crtfc_key": self.api_key, "corp_code": corp_code,
            "bsns_year": bsns_year, "reprt_code": reprt_code,
        })
        if not data:
            return ""

        revenue_kw      = ["매출액", "영업수익", "매출"]
        op_income_kw    = ["영업이익", "영업이익(손실)", "영업손실"]
        net_income_kw   = ["당기순이익", "당기순이익(손실)", "분기순이익", "반기순이익", "당기순손실"]

        summary: Dict[str, Optional[tuple]] = {"매출액": None, "영업이익": None, "당기순이익": None}

        for item in data:
            acc = item.get("account_nm", "").replace(" ", "")
            th  = item.get("thstg_amount")
            fr  = item.get("frmtrm_amount")
            if not th:
                continue
            if any(k in acc for k in revenue_kw) and not summary["매출액"]:
                summary["매출액"] = (th, fr)
            elif any(k in acc for k in op_income_kw) and not summary["영업이익"]:
                summary["영업이익"] = (th, fr)
            elif any(k in acc for k in net_income_kw) and not summary["당기순이익"]:
                summary["당기순이익"] = (th, fr)

        lines = []
        for key, val in summary.items():
            if val:
                th_fmt = self.format_korean_amount(val[0])
                fr_fmt = self.format_korean_amount(val[1]) if val[1] else "-"
                pct = self._calc_pct(val[0], val[1])
                lines.append(f"{key}: 당기 {th_fmt} / 전기 {fr_fmt}{pct}")
            else:
                lines.append(f"{key}: 정보 없음")

        return "\n".join(lines) + "\n"

    # ══════════════════════════════════════════════════════════════════
    # 유틸리티
    # ══════════════════════════════════════════════════════════════════

    def format_korean_amount(self, val_str: str) -> str:
        """숫자 문자열 → 한글 단위 금액 (예: '45400000000' → '454억 원')."""
        if not val_str:
            return "0원"
        clean = re.sub(r"[,\s]", "", str(val_str))
        negative = clean.startswith("-")
        clean = clean.lstrip("-")
        if not clean.isdigit():
            return val_str
        val = int(clean)
        if val == 0:
            return "0원"
        parts = []
        if val >= 1_000_000_000_000:
            parts.append(f"{val // 1_000_000_000_000}조"); val %= 1_000_000_000_000
        if val >= 100_000_000:
            parts.append(f"{val // 100_000_000}억");       val %= 100_000_000
        if val >= 10_000:
            parts.append(f"{val // 10_000:,}만");          val %= 10_000
        parts.append("원")
        return ("-" if negative else "") + " ".join(parts)

    def _calc_pct(self, current: str, previous: str) -> str:
        """전기 대비 증감률 문자열 반환."""
        try:
            c = float(re.sub(r"[,\s]", "", str(current)))
            p = float(re.sub(r"[,\s]", "", str(previous)))
            if p != 0:
                return f" ({(c - p) / abs(p) * 100:+.1f}%)"
        except Exception:
            pass
        return ""

    def _fmt_num(self, raw: str, suffix: str = "") -> str:
        """숫자 문자열을 정수 콤마 포맷 + suffix로 변환."""
        clean = re.sub(r"[,\s]", "", str(raw or ""))
        if clean.isdigit():
            return f"{int(clean):,}{suffix}"
        return raw or "정보 없음"

    def _extract_amount_from_cell(self, cell_text: str) -> Optional[str]:
        """셀 텍스트에서 금액 숫자만 추출합니다.
        '- 계약금액 : 6,640,000,000원' → '6640000000'
        '6,640,000,000' → '6640000000'
        """
        # 콤마 포함 7자리 이상 숫자 추출 (금액)
        m = re.search(r"[\d,]{7,}", cell_text)
        if m:
            return re.sub(r"[,\s]", "", m.group())
        return None

    def _extract_pct_from_cell(self, cell_text: str) -> Optional[str]:
        """셀 텍스트에서 퍼센트 숫자 추출합니다.
        '- 매출액 대비 : 11.28' → '11.28'
        """
        m = re.search(r"(?:매출액\s*대비|대비)\s*[:\s]\s*([\d.]+)", cell_text)
        if m:
            return m.group(1)
        return None

    def format_amount_with_suffix(self, val_str: str) -> str:
        """금액을 '원래숫자 (한글단위)' 형태로 반환.
        1조 이상:  (X조 X,XXX억 원) 형태  예: 3,090,076,756,644 → ... (3조 900억 원)
        1억 이상:  (X,XXX억 원) 형태      예: 130,000,000,000 → ... (1,300억 원)
        1억 미만:  (X,XXX만 원) 형태      예: 83,000,000 → ... (8,300만 원)
        숫자가 아니거나 0이면 원본 반환.
        """
        if not val_str:
            return "-"
        clean = re.sub(r"[,\s]", "", str(val_str))
        neg = clean.startswith("-")
        abs_clean = clean.lstrip("-")
        if not abs_clean.isdigit():
            return val_str
        n = int(abs_clean)
        if n == 0:
            return "0원"
        formatted_num = ("-" if neg else "") + f"{n:,}"

        # 1조 이상: 조 + 억 단위 표시
        if n >= 1_000_000_000_000:
            jo  = n // 1_000_000_000_000
            rem = (n % 1_000_000_000_000) // 100_000_000
            if rem:
                korean = f"{jo:,}조 {rem:,}억 원"
            else:
                korean = f"{jo:,}조 원"
        # 1억 이상: 억 단위만 표시
        elif n >= 100_000_000:
            eok = n // 100_000_000
            korean = f"{eok:,}억 원"
        # 1만 이상 1억 미만: 만 단위 표시
        elif n >= 10_000:
            man = n // 10_000
            korean = f"{man:,}만 원"
        else:
            korean = f"{n:,}원"

        return f"{formatted_num} ({korean})"

    # ══════════════════════════════════════════════════════════════════
    # 공시별 룰 기반 포맷터
    # ══════════════════════════════════════════════════════════════════

    def build_rule_based_summary(self, category: str, api_type: str,
                                  details: List[Dict[str, Any]], report_name: str) -> str:
        """DART JSON API 응답을 공시 유형별로 정형화된 요약 텍스트로 변환합니다."""
        if not details:
            return ""
        item = details[0]

        # ── 유상증자결정
        if api_type == "piicDecsn":
            nstk_cnt  = item.get("nstk_ostk_cnt") or item.get("nstk_estk_cnt")
            ic_mthn   = item.get("ic_mthn", "-")
            # 핵심 필드가 모두 비어있으면 HTML fallback
            if not nstk_cnt and ic_mthn == "-":
                return ""

            def _fmt_fdpp(v):
                """자금조달 금액: 숫자가 아니거나 0/-이면 None 반환"""
                if not v or str(v).strip() in ("-", "0", ""):
                    return None
                clean = re.sub(r"[,\s]", "", str(v))
                if clean.isdigit() and int(clean) > 0:
                    return self.format_amount_with_suffix(str(int(clean)))
                return None

            # 자금조달 목적별 금액 집계
            fdpp_fields = [
                ("시설자금",          item.get("fdpp_fclt")),
                ("운영자금",          item.get("fdpp_op")),
                ("채무상환자금",      item.get("fdpp_dtrp")),
                ("타법인증권취득자금", item.get("fdpp_ocsa")),
                ("영업양수자금",      item.get("fdpp_bsninh")),
                ("기타자금",          item.get("fdpp_etc")),
            ]
            total_fund = 0
            for _, v in fdpp_fields:
                try:
                    total_fund += int(re.sub(r"[,\s]", "", str(v or "0")) or 0)
                except Exception:
                    pass

            lines = [f"증자방식: {ic_mthn}"]

            # 신주 발행수
            ostk = item.get("nstk_ostk_cnt")
            estk = item.get("nstk_estk_cnt")
            if ostk and ostk != "-":
                lines.append(f"신주수(보통주): {self._fmt_num(ostk, '주')}")
            if estk and estk != "-":
                lines.append(f"신주수(기타주식): {self._fmt_num(estk, '주')}")

            # 증자전 발행주식 총수
            bfic_ostk = item.get("bfic_tisstk_ostk")
            if bfic_ostk and bfic_ostk != "-":
                lines.append(f"증자전 발행주식(보통주): {self._fmt_num(bfic_ostk, '주')}")

            # 자금조달 합계 및 목적별 내역
            if total_fund > 0:
                lines.append(f"자금조달 합계: {self.format_amount_with_suffix(str(total_fund))}")
            for label, v in fdpp_fields:
                fmt = _fmt_fdpp(v)
                if fmt:
                    lines.append(f"  - {label}: {fmt}")

            # 공매도
            ssl_at = item.get("ssl_at", "-")
            ssl_bgd = item.get("ssl_bgd", "-")
            ssl_edd = item.get("ssl_edd", "-")
            if ssl_at and ssl_at not in ("-", ""):
                lines.append(f"공매도 해당여부: {ssl_at}")
            if ssl_bgd and ssl_bgd != "-":
                lines.append(f"공매도 기간: {ssl_bgd} ~ {ssl_edd}")

            # 이사회결의일
            bddd = item.get("bddd", "-")
            if bddd and bddd != "-":
                lines.append(f"이사회결의일: {bddd}")

            return "\n".join(lines)

        # ── 무상증자결정
        elif api_type == "fricDecsn":
            ostk = item.get("nstk_ostk_cnt")
            asstd = item.get("nstk_asstd", "-")
            # 핵심 필드가 모두 비어있으면 HTML fallback
            if not ostk and asstd == "-":
                return ""

            lines = []
            # 신주 발행수
            if ostk and ostk != "-":
                lines.append(f"신주수(보통주): {self._fmt_num(ostk, '주')}")
            estk = item.get("nstk_estk_cnt")
            if estk and estk != "-":
                lines.append(f"신주수(기타주식): {self._fmt_num(estk, '주')}")

            # 증자전 발행주식
            bfic_ostk = item.get("bfic_tisstk_ostk")
            if bfic_ostk and bfic_ostk != "-":
                lines.append(f"증자전 발행주식(보통주): {self._fmt_num(bfic_ostk, '주')}")

            # 배정 비율
            ratio_ostk = item.get("nstk_ascnt_ps_ostk", "-")
            if ratio_ostk and ratio_ostk != "-":
                lines.append(f"1주당 신주배정(보통주): {ratio_ostk}주")

            # 일정
            lines.append(f"신주배정기준일: {asstd}")
            nstk_dividrk = item.get("nstk_dividrk", "-")
            if nstk_dividrk and nstk_dividrk != "-":
                lines.append(f"배당기산일: {nstk_dividrk}")
            nstk_dlprd = item.get("nstk_dlprd", "-")
            if nstk_dlprd and nstk_dlprd != "-":
                lines.append(f"신주권교부예정일: {nstk_dlprd}")
            nstk_lstprd = item.get("nstk_lstprd", "-")
            if nstk_lstprd and nstk_lstprd != "-":
                lines.append(f"신주 상장 예정일: {nstk_lstprd}")

            bddd = item.get("bddd", "-")
            if bddd and bddd != "-":
                lines.append(f"이사회결의일: {bddd}")

            return "\n".join(lines) if lines else ""

        # ── 감자결정
        elif api_type == "crDecsn":
            cr_mth = item.get("cr_mth", "-")
            cr_rs  = item.get("cr_rs", "-")
            bfcr_cpt = item.get("bfcr_cpt", "-")
            atcr_cpt = item.get("atcr_cpt", "-")
            cr_rt_ostk = item.get("cr_rt_ostk", "-")
            cr_std = item.get("cr_std", "-")

            # 핵심 필드 모두 비어있으면 HTML fallback
            if cr_mth == "-" and bfcr_cpt == "-" and cr_rt_ostk == "-":
                return ""

            lines = []
            # 자본금 변동
            if bfcr_cpt and bfcr_cpt != "-":
                clean_bfcr = re.sub(r'[,\s]', '', str(bfcr_cpt))
                lines.append(f"감자전 자본금: {self.format_amount_with_suffix(clean_bfcr)}")
            if atcr_cpt and atcr_cpt != "-":
                clean_atcr = re.sub(r'[,\s]', '', str(atcr_cpt))
                lines.append(f"감자후 자본금: {self.format_amount_with_suffix(clean_atcr)}")

            # 감자 비율
            if cr_rt_ostk and cr_rt_ostk != "-":
                lines.append(f"감자비율(보통주): {cr_rt_ostk}%")
            cr_rt_estk = item.get("cr_rt_estk", "-")
            if cr_rt_estk and cr_rt_estk not in ("-", ""):
                lines.append(f"감자비율(기타주식): {cr_rt_estk}%")

            # 감자할 주식수
            crstk_ostk = item.get("crstk_ostk_cnt", "-")
            if crstk_ostk and crstk_ostk != "-":
                lines.append(f"감자주식수(보통주): {self._fmt_num(crstk_ostk, '주')}")
            crstk_estk = item.get("crstk_estk_cnt", "-")
            if crstk_estk and crstk_estk not in ("-", ""):
                lines.append(f"감자주식수(기타주식): {self._fmt_num(crstk_estk, '주')}")

            # 발행주식 수 변동
            bfcr_tisstk = item.get("bfcr_tisstk_ostk", "-")
            atcr_tisstk = item.get("atcr_tisstk_ostk", "-")
            if bfcr_tisstk and bfcr_tisstk != "-":
                lines.append(f"발행주식수 변동(보통주): {self._fmt_num(bfcr_tisstk, '주')} → {self._fmt_num(atcr_tisstk, '주')}")

            # 감자방법 / 사유
            if cr_mth and cr_mth != "-":
                lines.append(f"감자방법: {cr_mth}")
            if cr_rs and cr_rs != "-":
                lines.append(f"감자사유: {cr_rs}")

            # 감자기준일 및 일정
            if cr_std and cr_std != "-":
                lines.append(f"감자기준일: {cr_std}")

            crsc_trnmsppd = item.get("crsc_trnmsppd", "-")
            if crsc_trnmsppd and crsc_trnmsppd != "-":
                lines.append(f"명의개서정지기간: {crsc_trnmsppd}")



            return "\n".join(lines) if lines else ""

        # ── 전환사채권발행결정
        # 실제 API 필드명: bd_fta(총액), bd_intr_ex(표면이자율), bd_intr_sf(만기이자율)
        #                   cv_prc(전환가액), pymd(납입일), cvrqpd_bgd/edd(전환청구기간)
        elif api_type == "cvbdIsDecsn":
            totamt = item.get('bd_fta') or item.get('bd_totamt') or item.get('bd_pta_fta')
            if not totamt or str(totamt).strip() in ("-", "0", ""):
                return ""
            lines = [
                f"사채총액: {self.format_amount_with_suffix(str(totamt))}",
                f"표면/만기이자율: {item.get('bd_intr_ex') or item.get('bd_ofr_intrrt', '-')}% / {item.get('bd_intr_sf') or item.get('bd_exp_intrrt', '-')}%",
                f"전환가액: {self._fmt_num(item.get('cv_prc'), '원')}",
                f"납입일: {item.get('pymd') or item.get('pay_de', '-')}",
                f"전환청구기간: {item.get('cvrqpd_bgd') or item.get('cv_req_bgnde', '-')} ~ {item.get('cvrqpd_edd') or item.get('cv_req_endde', '-')}",
            ]
            # 사채 회차 정보 추가 (있는 경우)
            bd_tm = item.get('bd_tm', '')
            bd_knd = item.get('bd_knd', '')
            if bd_tm or bd_knd:
                lines.insert(0, f"사채종류: {bd_knd or '-'} ({bd_tm or '-'}차)")
            return "\n".join(lines)

        # ── 신주인수권부사채권발행결정
        # 실제 API 필드명: bd_fta(총액), bd_intr_ex(표면이자율), bd_intr_sf(만기이자율)
        #                   ex_prc(행사가액), pymd(납입일), exrqpd_bgd/edd(행사청구기간)
        elif api_type == "bdwtIsDecsn":
            totamt = item.get('bd_fta') or item.get('bd_totamt')
            return (
                f"사채총액: {self.format_amount_with_suffix(str(totamt)) if totamt else '-'}\n"
                f"표면/만기이자율: {item.get('bd_intr_ex') or item.get('bd_ofr_intrrt', '-')}% / {item.get('bd_intr_sf') or item.get('bd_exp_intrrt', '-')}%\n"
                f"행사가액: {self._fmt_num(item.get('ex_prc'), '원')}\n"
                f"납입일: {item.get('pymd') or item.get('pay_de', '-')}\n"
                f"행사청구기간: {item.get('exrqpd_bgd') or item.get('ex_req_bgnde', '-')} ~ {item.get('exrqpd_edd') or item.get('ex_req_endde', '-')}"
            )

        # ── 교환사채권발행결정
        # 실제 API 필드명: bd_fta(총액), bd_intr_ex(표면이자율), bd_intr_sf(만기이자율)
        #                   ex_prc(교환가액), pymd(납입일), exrqpd_bgd/edd(교환청구기간)
        elif api_type == "exbdIsDecsn":
            totamt = item.get('bd_fta') or item.get('bd_totamt')
            return (
                f"사채총액: {self.format_amount_with_suffix(str(totamt)) if totamt else '-'}\n"
                f"표면/만기이자율: {item.get('bd_intr_ex') or item.get('bd_ofr_intrrt', '-')}% / {item.get('bd_intr_sf') or item.get('bd_exp_intrrt', '-')}%\n"
                f"교환가액: {self._fmt_num(item.get('ex_prc'), '원')}\n"
                f"납입일: {item.get('pymd') or item.get('pay_de', '-')}\n"
                f"교환청구기간: {item.get('exrqpd_bgd') or item.get('ex_req_bgnde', '-')} ~ {item.get('exrqpd_edd') or item.get('ex_req_endde', '-')}"
            )

        # ── 회사합병결정
        elif api_type == "cmpMgDecsn":
            return (
                f"합병상대방: {item.get('mgr_corp', '-')}\n"
                f"합병방식: {item.get('mg_mth', '-')}\n"
                f"합병비율: {item.get('mg_rt', '-')}\n"
                f"합병기일: {item.get('mg_de', '-')}\n"
                f"합병목적: {item.get('mg_prp', '-')}"
            )

        # ── 회사분할결정
        elif api_type == "cmpDvDecsn":
            return (
                f"분할방식: {item.get('dv_mth', '-')}\n"
                f"분할비율: {item.get('dv_rt', '-')}\n"
                f"분할기일: {item.get('dv_de', '-')}\n"
                f"분할목적: {item.get('dv_prp', '-')}"
            )

        # ── 영업양수결정
        elif api_type == "bsnInhDecsn":
            return (
                f"양수대상: {item.get('inh_bsn', '-')}\n"
                f"양수금액: {self.format_korean_amount(item.get('aq_amount'))}\n"
                f"자산 대비 비율: {item.get('ast_tot_rt', '-')}%\n"
                f"양수예정일: {item.get('aq_expt_de', '-')}"
            )

        # ── 영업양도결정
        elif api_type == "bsnTrfDecsn":
            return (
                f"양도대상: {item.get('trf_bsn', '-')}\n"
                f"양도금액: {self.format_korean_amount(item.get('aq_amount'))}\n"
                f"자산 대비 비율: {item.get('ast_tot_rt', '-')}%\n"
                f"양도예정일: {item.get('trf_de', '-')}"
            )

        # ── 타법인 주식 취득/양도결정
        elif api_type in ("otcprStkInvscrInhDecsn", "otcprStkInvscrTrfDecsn"):
            obj = "취득" if api_type == "otcprStkInvscrInhDecsn" else "양도"
            return (
                f"{obj}대상: {item.get('inv_corp_nm', '-')} ({item.get('inv_corp_main_bsns', '-')})\n"
                f"{obj}금액: {self.format_korean_amount(item.get('aq_amount'))}\n"
                f"{obj} 후 지분율: {item.get('own_stk_rt', '-')}%\n"
                f"{obj}예정일: {item.get('aq_expt_de', '-')}\n"
                f"{obj}목적: {str(item.get('aq_prp', '-')).replace(chr(10), ' ').strip()}"
            )

        # ── 유형자산 양수/양도결정
        elif api_type in ("tgastInhDecsn", "tgastTrfDecsn"):
            obj = "양수" if api_type == "tgastInhDecsn" else "양도"
            return (
                f"{obj}금액: {self.format_korean_amount(item.get('aq_amount'))}\n"
                f"자산총액 대비: {item.get('ast_tot_rt', '-')}%\n"
                f"{obj}목적: {str(item.get('trf_prp', '-')).replace(chr(10), ' ').strip()}\n"
                f"{obj}기준일: {item.get('trf_de', '-')}"
            )

        # ── 자기주식 취득/처분결정
        # 실제 API 필드명: aqpln_stk_ostk(취득예정주식 보통주), aqpln_prc_ostk(취득예정금액 보통주)
        #                   aqexpd_bgd(취득예상기간 시작일), aqexpd_edd(종료일), aq_pp(취득목적), aq_mth(취득방법)
        elif api_type in ("tsstkAqDecsn", "tsstkDpDecsn"):
            obj = "취득" if api_type == "tsstkAqDecsn" else "처분"
            # 필드명: 신규 필드명 우선, 구 필드명 폴백
            stk_qty  = item.get('aqpln_stk_ostk') or item.get('aq_expt_stk_qy')
            stk_amt  = item.get('aqpln_prc_ostk') or item.get('aq_expt_amt')
            bgn_de   = item.get('aqexpd_bgd') or item.get('aq_bgnde', '-')
            end_de   = item.get('aqexpd_edd') or item.get('aq_endde', '-')
            purpose  = item.get('aq_pp') or item.get('aq_prp', '-')
            method   = item.get('aq_mth', '')
            lines = [
                f"{obj}대상: 자기주식 보통주 {self._fmt_num(stk_qty, '주')}",
                f"{obj}규모: {self.format_amount_with_suffix(str(stk_amt)) if stk_amt else '0원'}",
                f"{obj}기간: {bgn_de} ~ {end_de}",
                f"{obj}목적: {str(purpose).replace(chr(10), ' ').strip()}",
            ]
            if method and method != '-':
                lines.append(f"{obj}방법: {method}")
            return "\n".join(lines)

        # ── 소송제기
        elif api_type == "lwstLg":
            return (
                f"소송상대방: {item.get('lwst_prty', '-')}\n"
                f"소송금액: {self.format_korean_amount(item.get('lwst_dmnd_amt'))}\n"
                f"소송내용: {str(item.get('lwst_ctt', '-')).replace(chr(10), ' ').strip()[:100]}\n"
                f"소송기일: {item.get('lwst_de', '-')}"
            )

        # ── 부도발생
        elif api_type == "dfOcr":
            return (
                f"부도금액: {self.format_korean_amount(item.get('df_amt'))}\n"
                f"부도일: {item.get('df_de', '-')}\n"
                f"부도은행: {item.get('df_bnkn', '-')}"
            )

        # ── 영업정지
        elif api_type == "bsnSp":
            return (
                f"정지사유: {item.get('bsn_sp_rsn', '-')}\n"
                f"정지기간: {item.get('bsn_sp_bgnde', '-')} ~ {item.get('bsn_sp_endde', '-')}"
            )

        # ── 회생절차개시신청
        elif api_type == "ctrcvsBgrq":
            return (
                f"신청일: {item.get('ctrcvs_bgrq_de', '-')}\n"
                f"신청법원: {item.get('ctrcvs_bgrq_ct', '-')}"
            )

        # ── 해산사유
        elif api_type == "dsRsOcr":
            return f"해산사유: {item.get('ds_rs', '-')}\n해산일: {item.get('ds_de', '-')}"

        # ── 주식교환·이전결정
        elif api_type == "stkExtrDecsn":
            return (
                f"교환상대방: {item.get('extr_corp', '-')}\n"
                f"교환비율: {item.get('extr_rt', '-')}\n"
                f"교환기일: {item.get('extr_de', '-')}"
            )

        # ── 기타 (필드 최대 6개 나열)
        else:
            skip = {"rcept_no", "corp_code", "corp_cls", "corp_name", "stock_code"}
            lines, count = [], 0
            for k, v in item.items():
                if k in skip or not v or count >= 6:
                    continue
                lines.append(f"{self.FIELD_MAP.get(k, k)}: {v}")
                count += 1
            return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 단일판매·공급계약 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def parse_contract_html(self, html: str, report_name: str = "", rcept_dt: str = "") -> str:
        """
        단일판매·공급계약 HTML 파서.
        - [기재정정] 공시: 정정관련 공시서류제출일/정정사유/정정전후 비교 출력
        - 일반 체결 공시: rowspan 포함 표 구조에서 계약 핵심 정보 추출
        """
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")

        # 모든 행의 셀 텍스트를 수집 (빈 셀 제거)
        all_rows: List[List[str]] = []
        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if texts:
                all_rows.append(texts)

        if not all_rows:
            return self.extract_tables_from_html(html)

        if "기재정정" in report_name:
            return self._parse_correction_contract(all_rows, rcept_dt)
        else:
            return self._parse_normal_contract(all_rows)

    def _parse_normal_contract(self, rows: List[List[str]]) -> str:
        """일반 단일판매·공급계약체결 파싱 (rowspan 구조 대응)"""
        r: Dict[str, str] = {
            "계약구분": "", "체결계약명": "", "계약금액": "-",
            "매출액대비": "-", "계약상대": "-",
            "공급지역": "-", "시작일": "-", "종료일": "-",
            "수주일자": "-",
        }

        for row in rows:
            n = len(row)
            if n == 0:
                continue
            k0 = row[0].replace(" ", "")

            # 행 전체를 분석하여 수주일자 관련 키워드 검출
            row_clean_str = "".join(row).replace(" ", "")
            if any(kw in row_clean_str for kw in ["계약(수주)일자", "수주일자"]) and not any(skip in row_clean_str for skip in ["기간", "시작", "종료", "유보", "제출", "참고", "상기", "부가가치세"]):
                val_cand = row[-1].strip()
                # 긴 설명 문장이 아니고 날짜 패턴 또는 짧은 문자열일 때만 수주일자로 채움
                if len(val_cand) < 30 and not val_cand.startswith("-"):
                    r["수주일자"] = val_cand

            if n == 2:
                k, v = k0, row[1]
                if "판매" in k and "공급계약구분" in k:
                    r["계약구분"] = v
                elif "체결계약명" in k:
                    r["체결계약명"] = v
                elif "판매" in k and "공급계약" in k and "내용" in k:
                    r["체결계약명"] = v
                elif "계약금액" in k and ("원" in k or "금액" in k) and "최근" not in k:
                    r["계약금액"] = v
                elif "매출액대비" in k:
                    r["매출액대비"] = v
                elif "계약상대" in k and "관계" not in k:
                    r["계약상대"] = v
                elif ("판매" in k or "공급" in k) and "지역" in k:
                    r["공급지역"] = v
                elif "시작일" in k:
                    r["시작일"] = v
                elif "종료일" in k:
                    r["종료일"] = v

            elif n >= 3:
                k1 = row[1].replace(" ", "")
                v  = row[-1]
                if "계약내역" in k0 or "계약금액" in k0:
                    if "계약금액" in k1 and "최근" not in k1:
                        r["계약금액"] = v
                    elif "매출액대비" in k1:
                        r["매출액대비"] = v
                elif "계약기간" in k0:
                    if "시작일" in k1:
                        r["시작일"] = v
                    elif "종료일" in k1:
                        r["종료일"] = v
                # 2번째 셀 자체가 시작일/종료일인 경우
                if "시작일" in k1 and len(row) == 3:
                    r["시작일"] = row[2]
                elif "종료일" in k1 and len(row) == 3:
                    r["종료일"] = row[2]

        lines = []
        if r["계약구분"]:
            lines.append(f"계약구분: {r['계약구분']}")
        if r["체결계약명"]:
            lines.append(f"체결계약명: {r['체결계약명']}")
        lines.append(f"계약상대: {r['계약상대']}")
        lines.append(f"공급지역: {r['공급지역']}")
        lines.append(f"계약금액: {self.format_amount_with_suffix(r['계약금액'])}")
        lines.append(f"매출액대비: {r['매출액대비']}%")
        lines.append(f"계약기간: {r['시작일']} ~ {r['종료일']}")
        lines.append(f"수주일자: {r['수주일자']}")
        return "\n".join(lines)

    def _parse_correction_contract(self, rows: List[List[str]], rcept_dt: str = "") -> str:
        """[기재정정] 단일판매·공급계약 파싱 — 정정일자/정정사유/정정전후 비교 출력"""
        doc_type  = "-"
        doc_date  = "-"
        reason    = "-"
        corrections: List[tuple] = []   # (항목명, 정정전, 정정후)
        in_corrections = False

        for row in rows:
            n = len(row)
            if n == 0:
                continue

            joined = " ".join(row).replace(" ", "")

            # 1. 정정 메타 정보 탐색 (행 전체 텍스트 기반)
            if ("정정관련공시서류" in joined or "정정대상공시서류" in joined) and ("제출일" not in joined and "최초" not in joined):
                if doc_type == "-":
                    doc_type = row[-1]
            elif any(kw in joined for kw in ["공시서류제출일", "최초제출일", "제출일"]):
                if doc_date == "-":
                    doc_date = row[-1]
            elif "정정사유" in joined or "정정이유" in joined:
                if reason == "-":
                    reason = row[-1]
            elif "정정사항" in joined or "정정항목" in joined:
                in_corrections = True

            # 2. 정정전 / 정정후 항목 탐색
            if n >= 3:
                k0 = row[0].replace(" ", "")
                if "정정항목" in k0 or "항목" in k0:
                    in_corrections = True
                    continue
                if in_corrections:
                    corrections.append((row[0], row[1], row[2]))
            elif n == 2 and in_corrections:
                # 2열일 경우(항목명이 이전 행 생략): 전 값과 후 값만 존재하는 구조 대응
                pass

        # 정정일자: 기재정정 공시 접수일 (rcept_dt)
        rcept_display = "-"
        if rcept_dt:
            d = rcept_dt.replace("-", "")
            if len(d) == 8:
                rcept_display = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

        lines = []
        if rcept_display != "-":
            lines.append(f"정정일자: {rcept_display}")
        lines.append(f"정정관련 공시 서류 제출일: {doc_date}")
        lines.append(f"정정사유: {reason}")

        # 주요 항목 선별 출력
        for item, before, after in corrections:
            k = item.replace(" ", "")
            if "계약금액" in k:
                before_num = self._extract_amount_from_cell(before)
                after_num  = self._extract_amount_from_cell(after)
                if before_num and after_num:
                    lines.append(f"계약금액: {self.format_amount_with_suffix(before_num)} → {self.format_amount_with_suffix(after_num)}")
                    before_pct = self._extract_pct_from_cell(before)
                    after_pct  = self._extract_pct_from_cell(after)
                    if before_pct and after_pct:
                        b_p = before_pct if before_pct.endswith("%") else f"{before_pct}%"
                        a_p = after_pct if after_pct.endswith("%") else f"{after_pct}%"
                        lines.append(f"매출액대비: {b_p} → {a_p}")
                else:
                    lines.append(f"계약금액: {before} → {after}")
            elif "매출액대비" in k:
                b_p = before if str(before).endswith("%") else f"{before}%"
                a_p = after if str(after).endswith("%") else f"{after}%"
                lines.append(f"매출액대비: {b_p} → {a_p}")
            elif "계약기간종료일" in k or "종료일" in k:
                lines.append(f"계약기간 종료일: {before} → {after}")
            elif "시작일" in k:
                lines.append(f"계약기간 시작일: {before} → {after}")

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 중대재해 공시 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_disaster_html(self, html: str) -> str:
        """중대재해 발생 공시 HTML에서 핵심 정보를 추출합니다."""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")

        # 키워드 → 결과 매핑
        fields = {
            "발생장소":              None,
            "발생재해내용":          None,
            "사망자수":              None,
            "부상자수":              None,
            "중대재해발생일자":      None,
            "고용노동부보고일자":    None,
            "조치사항":              None,
        }
        label_map = {
            "발생장소":              "발생장소",
            "발생재해내용":          "발생재해내용",
            "재해의개요":            "발생재해내용",
            "사망자수":              "사망자수",
            "사망자":               "사망자수",
            "부상자수":              "부상자수",
            "부상자":               "부상자수",
            "중대재해발생일자":      "중대재해발생일자",
            "발생일자":             "중대재해발생일자",
            "고용노동부보고일자":    "고용노동부보고일자",
            "노동부보고일자":        "고용노동부보고일자",
            "조치사항":             "조치사항",
            "조치사항및향후대책":    "조치사항",
            "향후대책":             "조치사항",
        }

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue
            # 셀이 3개 이상인 경우(rowspan 구조): texts[0]이 대분류, texts[1]이 소분류 키
            # 예: ['1. 중대재해내용', '발생 장소', '에이치디현대엠엔에스(주)']
            for offset in range(min(2, len(texts) - 1)):
                k = texts[offset].replace(" ", "")
                v = texts[offset + 1] if offset + 1 < len(texts) else ""
                matched = False
                for keyword, field_key in label_map.items():
                    if keyword in k and fields[field_key] is None:
                        # offset=0이면 v=texts[1], offset=1이면 v=texts[2]
                        val = texts[offset + 1] if offset == 0 and len(texts) > offset + 1 else texts[-1]
                        fields[field_key] = val
                        matched = True
                        break
                if matched:
                    break

        display_labels = {
            "발생장소":           "발생장소",
            "발생재해내용":       "발생재해내용",
            "사망자수":           "사망자 수",
            "부상자수":           "부상자 수",
            "중대재해발생일자":   "중대재해 발생일자",
            "고용노동부보고일자": "고용노동부 보고일자",
            "조치사항":           "조치사항 및 향후 대책",
        }
        lines = []
        for fk, label in display_labels.items():
            lines.append(f"{label}: {fields[fk] or '-'}")
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 일반 주식소각결정 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_share_retirement_normal(self, html: str) -> str:
        """일반 주식소각결정 HTML 파서"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        r = {
            "소각주식수": "-",
            "소각예정금액": "-",
            "시작일": "-",
            "종료일": "-",
            "소각예정일": "-",
            "이사회결의일": "-"
        }

        current_main_key = ""

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if not texts:
                continue

            n = len(texts)
            k0 = texts[0].replace(" ", "")

            # 대분류 업데이트
            if "소각할주식" in k0:
                current_main_key = "소각주식"
            elif "발행주식" in k0:
                current_main_key = "발행주식"
            elif "취득예정기간" in k0 or "취득예정일" in k0:
                current_main_key = "취득기간"

            # 3열 구조 대응
            if n >= 3:
                k1 = texts[1].replace(" ", "")
                val = texts[-1]
                if current_main_key == "소각주식" and "보통주식" in k1:
                    r["소각주식수"] = val
                elif current_main_key == "취득기간":
                    if "시작일" in k1:
                        r["시작일"] = val
                    elif "종료일" in k1:
                        r["종료일"] = val
            # 2열 구조 대응
            elif n == 2:
                k, v = k0, texts[1]
                if "소각예정금액" in k:
                    r["소각예정금액"] = v
                elif "소각예정일" in k:
                    r["소각예정일"] = v
                elif "이사회결의일" in k:
                    r["이사회결의일"] = v
                elif "시작일" in k:
                    r["시작일"] = v
                elif "종료일" in k:
                    r["종료일"] = v

        # 결과 텍스트 구성 (요청사항 반영: 발행주식총수, 사외이사 등 제외)
        lines = []
        if r["소각주식수"] != "-":
            lines.append(f"소각할 주식 수: 보통주 {self._fmt_num(r['소각주식수'], '주')}")
        if r["소각예정금액"] != "-":
            lines.append(f"소각예정금액: {self.format_amount_with_suffix(r['소각예정금액'])}")
        if r["소각예정일"] != "-":
            # 앞의 숫자 번호 제거
            retirement_date = re.sub(r"^\d+\.\s*", "", r['소각예정일'])
            lines.append(f"소각 예정일: {retirement_date}")
        if r["이사회결의일"] != "-":
            lines.append(f"이사회결의일: {r['이사회결의일']}")
        if r["시작일"] != "-" or r["종료일"] != "-":
            lines.append(f"자기주식 취득 예정기간 : {r['시작일']} ~ {r['종료일']}")

        if not lines:
            return self.extract_tables_from_html(html)

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 기재정정 공시 공통 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_correction_common(self, html: str, report_name: str, rcept_dt: str = "") -> str:
        """기재정정 공시 공통 파서 (주식소각, 유상증자, 감자결정 등)"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        
        doc_type = "-"
        doc_date = "-"
        reason = "-"
        corrections = []
        
        # 1. 정정 메타 정보 추출
        # 실제 DART HTML에서 헤더 파싱 (숫자 접두어는 .replace("","") 후 비교)
        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if not texts or len(texts) < 2:
                continue

            k0 = texts[0].replace(" ", "")
            # 숙자 접두어 제거 (예: "1.", "2.", "3." 등) 후 피어 비교
            k_bare = re.sub(r"^\d+\.?", "", k0).strip()

            # n 열에 관계없이 첫 번째 또는 두 번째 셀에서 값 추출
            v1 = texts[1] if len(texts) >= 2 else "-"
            v_last = texts[-1]

            if any(kw in k_bare for kw in ["\uc815\uc815\ub300\uc0c1\uacf5\uc2dc\uc11c\ub958", "\uc815\uc815\uad00\ub828\uacf5\uc2dc\uc11c\ub958"]) \
               and "\uc81c\ucd9c\uc77c" not in k_bare and "\ucd5c\ucd08" not in k_bare:
                # "1. \uc815\uc815\uad00\ub828 \uacf5\uc2dc\uc11c\ub958" \ud56d\ubaa9 (\ubcf4\uace0\uc11c \uc885\ub958)
                doc_type = v1
            elif any(kw in k_bare for kw in [
                "\uc815\uc815\ub300\uc0c1\uacf5\uc2dc\uc11c\ub958\uc758\ucd5c\ucd08\uc81c\ucd9c\uc77c",
                "\uc815\uc815\uad00\ub828\uacf5\uc2dc\uc11c\ub958\uc81c\ucd9c\uc77c",
                "\uc815\uc815\uad00\ub828\uacf5\uc2dc\uc11c\ub958\uc81c\ucd9c",
                "\ucd5c\ucd08\uc81c\ucd9c\uc77c",
            ]):
                doc_date = v1
            elif any(kw in k_bare for kw in ["\uc815\uc815\uc0ac\uc720", "\uc815\uc815\uc774\uc720"]):
                reason = v1

        # 2. 정정사항 비교 테이블만 타겟으로 수집 (정정전/정정후가 헤더나 내용에 포함된 테이블만)
        for table in soup.find_all("table"):
            table_text = table.get_text()
            if "정정전" in table_text and "정정후" in table_text:
                for tr in table.find_all(["tr", "TR"]):
                    cells = tr.find_all(["td", "th", "TD", "TH"])
                    texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
                    texts = [t for t in texts if t]
                    if len(texts) < 2:
                        continue
                        
                    k0 = texts[0].replace(" ", "")
                    # 헤더 행 제외
                    if any(h in k0 for h in ["정정항목", "항목", "정정전", "정정후"]):
                        continue

                    # 3열 이상: 항목명 | 정정전 | 정정후
                    if len(texts) >= 3:
                        item_name = texts[0]
                        val_before = texts[-2]
                        val_after = texts[-1]
                    # 2열: 정정전값 | 정정후값 (항목명이 이전 행의 rowspan)
                    else:
                        # 2열 구조는 항목명을 파악하기 어려우므로 스킵
                        continue
                        
                    if val_before == val_after:
                        continue
                    
                    # 항목명 앞의 번호 및 기호(예: '7. ', '1. ', '- ', '▶') 제거
                    item_name = re.sub(r"^[-\d\.\s*▶]+", "", item_name).strip()
                    
                    # 불필요하거나 오파싱된 본문 항목 필터링 (공백 제거 후 비교)
                    item_name_clean = item_name.replace(" ", "")
                    if any(x in item_name_clean for x in ["기타투자판단", "참고사항", "첨부", "삭제", "사외이사"]):
                        continue
                        
                    corrections.append((item_name, val_before, val_after))
                break # 정정사항 비교 테이블만 수집 후 중단

        # 3. 공시 유형 판단
        is_share_retirement = any(x in report_name or x in doc_type for x in ["주식소각", "소각"])
        is_capital_increase = any(x in report_name or x in doc_type for x in ["유상증자", "증자"])
        is_capital_reduction = any(x in report_name or x in doc_type for x in ["감자결정", "감자"])

        # 4. 요약 생성
        lines = []
        rcept_display = "-"
        if rcept_dt:
            d = rcept_dt.replace("-", "")
            if len(d) == 8:
                rcept_display = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                
        lines.append(f"정정일자: {rcept_display}")
        lines.append(f"정정관련 공시 서류 제출일: {doc_date}")
        lines.append(f"정정사유: {reason}")

        for item, before, after in corrections:
            clean_item = item.replace(" ", "")
            
            # 주식 소각 관련 정정 항목
            if is_share_retirement:
                if "소각할주식" in clean_item or "소각할주식의종류와수" in clean_item:
                    before_num = self._fmt_num(before, "주")
                    after_num = self._fmt_num(after, "주")
                    lines.append(f"소각할 주식 수 정정: {before_num} → {after_num}")
                elif "소각예정금액" in clean_item:
                    before_amt = self.format_amount_with_suffix(before)
                    after_amt = self.format_amount_with_suffix(after)
                    lines.append(f"소각예정금액: {before_amt} → {after_amt}")
                else:
                    lines.append(f"{item}: {before} → {after}")
                    
            # 유상증자 관련 정정 항목
            elif is_capital_increase:
                if any(kw in clean_item for kw in ["시설자금", "운영자금", "타법인", "채무상환", "기타자금"]):
                    before_amt = self.format_amount_with_suffix(before)
                    after_amt = self.format_amount_with_suffix(after)
                    lines.append(f"{item} 정정: {before_amt} → {after_amt}")
                elif "발행가액" in clean_item or "기준주가" in clean_item:
                    before_prc = self._fmt_num(before, "원")
                    after_prc = self._fmt_num(after, "원")
                    lines.append(f"{item} 정정: {before_prc} → {after_prc}")
                elif "발행주식" in clean_item or "증자주식" in clean_item:
                    before_num = self._fmt_num(before, "주")
                    after_num = self._fmt_num(after, "주")
                    lines.append(f"{item} 정정: {before_num} → {after_num}")
                else:
                    lines.append(f"{item}: {before} → {after}")
                    
            # 감자 관련 정정 항목
            elif is_capital_reduction:
                if "감자주식" in clean_item or "감자후주식" in clean_item:
                    before_num = self._fmt_num(before, "주")
                    after_num = self._fmt_num(after, "주")
                    lines.append(f"{item} 정정: {before_num} → {after_num}")
                elif "감자비율" in clean_item or "감자rt" in clean_item:
                    lines.append(f"{item} 정정: {before}% → {after}%")
                elif "감자예정일" in clean_item or "감자기준일" in clean_item:
                    lines.append(f"{item} 정정: {before} → {after}")
                else:
                    lines.append(f"{item}: {before} → {after}")
            
            # 그 외 공정공시 / 기타정정 공시 (단일판매 공급계약 기재정정 등)
            else:
                if "원" in clean_item or "금액" in clean_item:
                    before = self.format_amount_with_suffix(before)
                    after = self.format_amount_with_suffix(after)
                elif "주" in clean_item or "수" in clean_item:
                    before = self._fmt_num(before, "주")
                    after = self._fmt_num(after, "주")
                lines.append(f"{item}: {before} → {after}")

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 일반 유상증자결정 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_capital_increase_normal(self, html: str) -> str:
        """일반 유상증자결정 HTML 파서"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        r = {
            "증자방식": "-",
            "신주수": "-",
            "발행가액": "-",
            "납입일": "-",
            "상장예정일": "-",
            "시설자금": "-",
            "운영자금": "-",
            "타법인자금": "-",
            "채무상환자금": "-",
            "기타자금": "-"
        }

        current_main_key = ""

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if not texts:
                continue

            n = len(texts)
            k0 = texts[0].replace(" ", "")

            if "신주의종류와수" in k0:
                current_main_key = "신주수"
            elif "자금조달의목적" in k0:
                current_main_key = "자금목적"
            elif "신주발행가액" in k0:
                current_main_key = "발행가액"

            if n >= 3:
                k1 = texts[1].replace(" ", "")
                val = texts[-1]
                if current_main_key == "신주수" and "보통주식" in k1:
                    r["신주수"] = val
                elif current_main_key == "자금목적":
                    if "시설자금" in k1:
                        r["시설자금"] = val
                    elif "운영자금" in k1:
                        r["운영자금"] = val
                    elif "타법인" in k1:
                        r["타법인자금"] = val
                    elif "채무상환" in k1:
                        r["채무상환자금"] = val
                    elif "기타자금" in k1:
                        r["기타자금"] = val
                elif current_main_key == "발행가액" and "보통주식" in k1:
                    r["발행가액"] = val
            elif n == 2:
                k, v = k0, texts[1]
                if "증자방식" in k or "증자방법" in k or "배정방법" in k:
                    r["증자방식"] = v
                elif "납입일" in k:
                    r["납입일"] = v
                elif "상장예정일" in k:
                    r["상장예정일"] = v
                elif "발행가액" in k and current_main_key != "발행가액":
                    r["발행가액"] = v
                elif "신주의종류와수" in k:
                    r["신주수"] = v

        lines = []
        if r["증자방식"] != "-":
            lines.append(f"증자방식: {r['증자방식']}")
            
        cptl_list = []
        for key in ["시설자금", "운영자금", "타법인자금", "채무상환자금", "기타자금"]:
            if r[key] != "-":
                try:
                    cptl_list.append(int(re.sub(r"[,\s]", "", r[key])))
                except Exception:
                    pass
        if cptl_list:
            tot_amt = sum(cptl_list)
            lines.append(f"발행규모: {self.format_amount_with_suffix(str(tot_amt))} (보통주 {self._fmt_num(r['신주수'], '주')})")
        elif r["신주수"] != "-":
            lines.append(f"발행규모: 보통주 {self._fmt_num(r['신주수'], '주')}")
            
        if r["발행가액"] != "-":
            lines.append(f"발행가액: {self._fmt_num(r['발행가액'], '원')}")
        if r["납입일"] != "-":
            lines.append(f"납입일: {r['납입일']}")
        if r["상장예정일"] != "-":
            lines.append(f"신주상장예정일: {r['상장예정일']}")

        if not lines:
            return self.extract_tables_from_html(html)

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 일반 감자결정 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_capital_reduction_normal(self, html: str) -> str:
        """일반 감자결정 HTML 파서"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        r = {
            "감자방식": "-",
            "감자주식수": "-",
            "감자비율": "-",
            "감자예정일": "-"
        }

        current_main_key = ""

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if not texts:
                continue

            n = len(texts)
            k0 = texts[0].replace(" ", "")

            if "감자할주식" in k0:
                current_main_key = "감자주식"

            if n >= 3:
                k1 = texts[1].replace(" ", "")
                val = texts[-1]
                if current_main_key == "감자주식" and "보통주식" in k1:
                    r["감자주식수"] = val
            elif n == 2:
                k, v = k0, texts[1]
                if "감자방법" in k or "감자방식" in k:
                    r["감자방식"] = v
                elif "감자비율" in k:
                    r["감자비율"] = v
                elif "감자예정일" in k or "감자기준일" in k:
                    r["감자예정일"] = v
                elif "감자할주식" in k:
                    r["감자주식수"] = v

        lines = []
        if r["감자방식"] != "-":
            lines.append(f"감자방식: {r['감자방식']}")
        if r["감자주식수"] != "-":
            lines.append(f"감자주식수: 보통주 {self._fmt_num(r['감자주식수'], '주')}")
        if r["감자비율"] != "-":
            lines.append(f"감자비율: {r['감자비율']}%" if "%" not in r['감자비율'] else f"감자비율: {r['감자비율']}")
        if r["감자예정일"] != "-":
            lines.append(f"감자예정일: {r['감자예정일']}")

        if not lines:
            return self.extract_tables_from_html(html)

        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 자회사 주요경영사항 HTML 파서
    # ══════════════════════════════════════════════════════════════════

    def _parse_subsidiary_html(self, html: str, report_name: str) -> str:
        """
        자회사 주요경영사항 공시(800번대) HTML 파서.
        핵심 정보를 표에서 추출하여 구조화된 요약 텍스트로 반환합니다.
        - 자기주식취득결정, 주식소각결정 등 자회사 공시 대응
        """
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        all_rows: List[List[str]] = []
        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if texts:
                all_rows.append(texts)

        if not all_rows:
            return self.extract_tables_from_html(html)

        name_clean = report_name.replace(" ", "")

        # 자기주식취득결정 자회사 공시
        if "자기주식취득결정" in name_clean:
            return self._parse_subsidiary_treasury_stock(all_rows)
        # 주식소각결정 자회사 공시
        elif "주식소각결정" in name_clean:
            return self._parse_subsidiary_share_retirement(all_rows)
        else:
            # 그 외: 자회사 정보 + 핵심 표 항목 추출
            return self._parse_subsidiary_generic(all_rows)

    def _parse_subsidiary_treasury_stock(self, rows: List[List[str]]) -> str:
        """자회사 자기주식취득결정 HTML 파서"""
        r = {
            "자회사명": "-",
            "취득예정주식": "-",
            "취득예정금액": "-",
            "취득예상기간": "-",
            "취득목적": "-",
            "취득방법": "-",
        }
        aq_start = "-"
        aq_end = "-"

        # 자회사명 추출 ("자회사인 X 의 주요경영사항신고" 패턴)
        for row in rows:
            joined = " ".join(row)
            m = re.search(r"자회사인\s*(.+?)\s*의\s*주요경영사항", joined)
            if m:
                r["자회사명"] = m.group(1).strip()
                break

        current_main_key = ""
        for row in rows:
            n = len(row)
            if n == 0:
                continue
            k0 = row[0].replace(" ", "")

            # 대분류 상태 갱신
            if "취득예상기간" in k0:
                current_main_key = "취득예상기간"
            elif "취득예정주식" in k0:
                current_main_key = "취득예정주식"
            elif "취득예정금액" in k0:
                current_main_key = "취득예정금액"
            elif k0 and not any(kw in k0 for kw in ["종료일", "시작일"]):
                # 다른 항목으로 넘어가면 리셋
                if not any(kw in k0 for kw in ["취득예상기간", "취득예정주식", "취득예정금액"]):
                    if any(kw in k0 for kw in ["취득목적", "취득방법", "위탁", "보유현황", "취득결정일", "주문"]):
                        current_main_key = ""

            if n == 2:
                k, v = k0, row[1]
                # 종료일 독립 행 ("3. 취득예상기간" 다음 행에 "종료일 | 값" 형태)
                if "종료일" in k and current_main_key == "취득예상기간":
                    aq_end = v
                # 첫 값 우선(first-wins): 이미 값이 있으면 덮어쓰지 않음
                elif "취득목적" in k and r["취득목적"] == "-":
                    r["취득목적"] = v
                elif "취득방법" in k and r["취득방법"] == "-":
                    r["취득방법"] = v
            elif n >= 3:
                k1 = row[1].replace(" ", "")
                val = row[-1]
                if "취득예정주식" in k0 and "보통주식" in k1:
                    r["취득예정주식"] = val
                elif "취득예정금액" in k0 and "보통주식" in k1:
                    r["취득예정금액"] = val
                elif "취득예상기간" in k0 and "시작일" in k1:
                    aq_start = val
                elif ("취득예상기간" in k0 or current_main_key == "취득예상기간") and "종료일" in k1:
                    aq_end = val
                elif "취득목적" in k0 and r["취득목적"] == "-":
                    r["취득목적"] = row[1] if n == 3 else val
                elif "취득방법" in k0 and r["취득방법"] == "-":
                    # n==3 이면 두 번째 셀(값), n>3 이면 마지막 셀 사용
                    # 단, 마지막 셀이 "비고" 같은 의미없는 값이면 두 번째 셀 사용
                    candidate = row[1] if n >= 3 else val
                    if candidate and candidate != "비고" and candidate != "-":
                        r["취득방법"] = candidate
                    elif n > 3 and val and val != "비고" and val != "-":
                        r["취득방법"] = val

        if aq_start != "-" or aq_end != "-":
            r["취득예상기간"] = f"{aq_start} ~ {aq_end}"

        lines = []
        if r["자회사명"] != "-":
            lines.append(f"자회사: {r['자회사명']}")
        if r["취득예정주식"] != "-":
            lines.append(f"취득예정주식(보통주): {self._fmt_num(r['취득예정주식'], '주')}")
        if r["취득예정금액"] != "-":
            lines.append(f"취득예정금액: {self.format_amount_with_suffix(r['취득예정금액'])}")
        if r["취득예상기간"] != "-":
            lines.append(f"취득예상기간: {r['취득예상기간']}")
        if r["취득목적"] != "-":
            lines.append(f"취득목적: {r['취득목적']}")
        if r["취득방법"] != "-":
            lines.append(f"취득방법: {r['취득방법']}")

        return "\n".join(lines) if lines else self.extract_tables_from_html("\n".join(str(r) for r in rows))

    def _parse_subsidiary_share_retirement(self, rows: List[List[str]]) -> str:
        """자회사 주식소각결정 HTML 파서"""
        r = {
            "자회사명": "-",
            "소각주식수": "-",
            "소각예정금액": "-",
            "소각예정일": "-",
            "소각목적": "-",
        }

        for row in rows:
            joined = " ".join(row)
            m = re.search(r"자회사인\s*(.+?)\s*의\s*주요경영사항", joined)
            if m:
                r["자회사명"] = m.group(1).strip()
                break

        current_main_key = ""
        for row in rows:
            n = len(row)
            if n == 0:
                continue
            k0 = row[0].replace(" ", "")

            if "소각할주식" in k0:
                current_main_key = "소각주식"

            if n >= 3:
                k1 = row[1].replace(" ", "")
                val = row[-1]
                if current_main_key == "소각주식" and "보통주식" in k1:
                    r["소각주식수"] = val
            elif n == 2:
                k, v = k0, row[1]
                if "소각예정금액" in k:
                    r["소각예정금액"] = v
                elif "소각예정일" in k:
                    r["소각예정일"] = re.sub(r"^\d+\.\s*", "", v)
                elif "소각목적" in k or "소각방법" in k:
                    r["소각목적"] = v

        lines = []
        if r["자회사명"] != "-":
            lines.append(f"자회사: {r['자회사명']}")
        if r["소각주식수"] != "-":
            lines.append(f"소각할 주식 수: 보통주 {self._fmt_num(r['소각주식수'], '주')}")
        if r["소각예정금액"] != "-":
            lines.append(f"소각예정금액: {self.format_amount_with_suffix(r['소각예정금액'])}")
        if r["소각예정일"] != "-":
            lines.append(f"소각 예정일: {r['소각예정일']}")
        if r["소각목적"] != "-":
            lines.append(f"소각목적: {r['소각목적']}")

        return "\n".join(lines) if lines else self.extract_tables_from_html("\n".join(str(r) for r in rows))

    def _parse_subsidiary_generic(self, rows: List[List[str]]) -> str:
        """기타 자회사 주요경영사항 공시 HTML 파서 — 자회사명 + 주요 KV 쌍 추출"""
        sub_name = "-"
        for row in rows:
            joined = " ".join(row)
            m = re.search(r"자회사인\s*(.+?)\s*의\s*주요경영사항", joined)
            if m:
                sub_name = m.group(1).strip()
                break

        lines = []
        if sub_name != "-":
            lines.append(f"자회사: {sub_name}")

        skip_keywords = ["금융위원회", "한국거래소", "귀중", "홈페이지", "전화", "작성책임자", "직책", "성명"]
        count = 0
        for row in rows:
            if count >= 8:
                break
            if len(row) < 2:
                continue
            k = row[0].replace(" ", "")
            v = row[-1].strip()
            if not k or not v:
                continue
            if any(sk in k for sk in skip_keywords):
                continue
            # 번호로 시작하는 항목만 추출 (1. 2. 3. ... 형태)
            if re.match(r"^\d+\.?", k):
                item_name = re.sub(r"^\d+\.\s*", "", row[0]).strip()
                lines.append(f"{item_name}: {v}")
                count += 1

        return "\n".join(lines) if len(lines) > 1 else self.extract_tables_from_html("<br>".join([" | ".join(r) for r in rows]))

    def _parse_other_corp_acq_html(self, html: str) -> str:
        """타법인 주식 및 출자증권 취득결정 HTML 파서"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        r = {
            "회사명": "-",
            "국적": "-",
            "자본금": "-",
            "회사와의 관계": "-",
            "발행주식총수": "-",
            "취득주식수": "-",
            "취득금액": "-",
            "자기자본대비": "-",
            "취득 후 지분비율": "-",
        }

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue

            for i in range(len(texts) - 1):
                k = texts[i].replace(" ", "")
                v = texts[i + 1]

                if "회사명" in k and r["회사명"] == "-":
                    r["회사명"] = v
                elif "국적" in k and r["국적"] == "-":
                    r["국적"] = v
                elif "자본금" in k and r["자본금"] == "-":
                    r["자본금"] = self.format_amount_with_suffix(v)
                elif ("회사와관계" in k or "회사과의관계" in k) and r["회사와의 관계"] == "-":
                    r["회사와의 관계"] = v
                elif "발행주식총수" in k and r["발행주식총수"] == "-":
                    r["발행주식총수"] = self._fmt_num(v, "주")
                elif "취득주식수" in k and r["취득주식수"] == "-":
                    r["취득주식수"] = self._fmt_num(v, "주")
                elif "취득금액" in k and r["취득금액"] == "-":
                    r["취득금액"] = self.format_amount_with_suffix(v)
                elif "자기자본대비" in k and r["자기자본대비"] == "-":
                    v_clean = v.replace("%", "").strip()
                    r["자기자본대비"] = f"{v_clean}%" if v_clean != "-" else "-"
                elif "지분비율" in k and "소유주식수" not in k and r["취득 후 지분비율"] == "-":
                    v_clean = v.replace("%", "").strip()
                    r["취득 후 지분비율"] = f"{v_clean}%" if v_clean != "-" else "-"

        lines = [
            f"회사명 : {r['회사명']}",
            f"국적 : {r['국적']}",
            f"자본금 : {r['자본금']}",
            f"회사와의 관계 : {r['회사와의 관계']}",
            f"발행주식총수 : {r['발행주식총수']}",
            "",
            f"취득주식수 : {r['취득주식수']}",
            f"취득금액 : {r['취득금액']}",
            f"자기자본대비 : {r['자기자본대비']}",
            f"취득 후 지분비율 : {r['취득 후 지분비율']}",
        ]
        return "\n".join(lines)

    def _parse_tangible_asset_disposal_html(self, html: str) -> str:
        """유형자산처분결정(종속회사의 주요경영사항 포함) HTML 파서"""
        if not html or html.startswith("❌"):
            return html or "본문 없음"

        soup = BeautifulSoup(html, "html.parser")
        r = {
            "처분목적물": "-",
            "처분금액": "-",
            "지배회사의 연결자산 총액 대비": "-",
            "거래 상대방": "-",
            "회사와의 관계": "-",
            "처분 목적": "-",
            "처분예정일자": "-",
        }

        for tr in soup.find_all(["tr", "TR"]):
            cells = tr.find_all(["td", "th", "TD", "TH"])
            texts = [re.sub(r"\s+", " ", c.get_text()).strip() for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 2:
                continue

            for i in range(len(texts) - 1):
                k = texts[i].replace(" ", "")
                v = texts[i + 1]

                if "처분목적물" in k and r["처분목적물"] == "-":
                    r["처분목적물"] = v
                elif "처분금액" in k and "대비" not in k and r["처분금액"] == "-":
                    r["처분금액"] = self.format_amount_with_suffix(v)
                elif ("연결자산총액대비" in k or "자산총액대비" in k) and r["지배회사의 연결자산 총액 대비"] == "-":
                    v_clean = v.replace("%", "").strip()
                    r["지배회사의 연결자산 총액 대비"] = f"{v_clean}%" if v_clean != "-" else "-"
                elif "거래상대방" in k and r["거래 상대방"] == "-":
                    r["거래 상대방"] = v
                elif ("회사와관계" in k or "회사과의관계" in k) and r["회사와의 관계"] == "-":
                    r["회사와의 관계"] = v
                elif "처분목적" in k and "처분목적물" not in k and r["처분 목적"] == "-":
                    r["처분 목적"] = v
                elif "처분예정일자" in k and r["처분예정일자"] == "-":
                    r["처분예정일자"] = re.sub(r"^\d+\.\s*", "", v)

        # 거래 상대방 (회사와의 관계) 형태로 조합
        rel = r["회사와의 관계"]
        counterparty = r["거래 상대방"]
        if counterparty != "-":
            counterparty_fmt = f"{counterparty} ({rel})"
        else:
            counterparty_fmt = "-"

        lines = [
            f"처분목적물 : {r['처분목적물']}",
            f"처분 금액 : {r['처분금액']}",
            f"지배회사의 연결자산 총액 대비 : {r['지배회사의 연결자산 총액 대비']}",
            f"거래 상대방 : {counterparty_fmt}",
            f"처분 목적 : {r['처분 목적']}",
            f"처분예정일자 : {r['처분예정일자']}",
        ]
        return "\n".join(lines)

    # ══════════════════════════════════════════════════════════════════
    # 공시 내용 통합 조회 (메인 진입점)
    # ══════════════════════════════════════════════════════════════════

    def get_announcement_content(self, ann: Dict[str, Any],
                                  save_html_dir: Optional[Path] = None) -> str:
        """
        공시 항목을 분석하여:
        1. JSON API 지원 → 룰 기반 포맷 텍스트 반환
        2. 단일판매·공급계약 → HTML 파서 적용
        3. 중대재해 → 전용 HTML 파서 적용
        4. 그 외 비정형 → 표 추출 텍스트 반환
        save_html_dir 가 지정된 경우 raw HTML을 해당 경로에 저장합니다.
        """
        corp_name   = ann.get("corp_name", "")
        report_name = ann.get("report_nm", "")
        rcept_no    = ann.get("rcept_no", "")
        corp_code   = ann.get("corp_code", "")
        rcept_dt    = ann.get("rcept_dt", "")
        date_str    = rcept_dt or datetime.date.today().strftime("%Y%m%d")

        # ── 1. JSON API 지원 공시 처리
        api_info = self.detect_json_api_type(ann)
        if api_info:
            category, api_type = api_info
            print(f"   💡 [JSON API] category={category}, type={api_type}")

            if category == "report":
                # 정기보고서: 사업연도 추출
                m = re.search(r"\((\d{4})\.\d{2}\)", report_name)
                bsns_year = m.group(1) if m else (
                    str(int(date_str[:4]) - 1) if len(date_str) >= 6 and int(date_str[4:6]) <= 3
                    else date_str[:4]
                )
                summary = self.get_finstate_summary(corp_code, bsns_year, api_type)
                if summary.strip():
                    return summary

            else:
                if category == "event":
                    details = self.get_event_json_details(corp_code, rcept_no, api_type, date_str)
                else:  # share
                    details = self.get_share_json_details(corp_code, rcept_no, api_type)

                if details:
                    summary = self.build_rule_based_summary(category, api_type, details, report_name)
                    if summary.strip():
                        return summary

            print("   ⚠️ JSON API 데이터 없음 → HTML 파싱으로 전환")

        # ── 2. HTML 다운로드
        raw_html = self._download_zip_html(rcept_no)

        # HTML 저장 (옵션)
        if save_html_dir and not raw_html.startswith("❌"):
            self.save_raw_html(rcept_no, corp_name, report_name, save_html_dir)

        # 공백 제거 등 전처리
        name_clean = report_name.replace(" ", "")
        name_normalized = name_clean.replace("ㆍ", "").replace("·", "")

        # ── 3. 단일판매·공급계약 전용 파서 (기재정정 포함, 가운뎃점 문자 종류 무관하게 매칭)
        if "단일판매" in name_normalized and "공급계약" in name_normalized:
            return self.parse_contract_html(raw_html, report_name, rcept_dt)

        # ── 4. 타법인 주식 및 출자증권 취득결정 전용 파서
        if "타법인" in name_clean and "취득결정" in name_clean:
            return self._parse_other_corp_acq_html(raw_html)

        # ── 4-1. 유형자산 처분결정 전용 파서 (종속회사의 주요경영사항 포함)
        if "유형자산처분" in name_clean:
            return self._parse_tangible_asset_disposal_html(raw_html)

        # ── 5. 그 외 [기재정정] 공시 처리
        if "정정" in name_clean:
            return self._parse_correction_common(raw_html, report_name, rcept_dt)

        # ── 6. 자회사 주요경영사항 전용 파서 (800번대 공시)
        # "(자회사의 주요경영사항)" 포함 공시는 전용 파서로 구조화 요약 출력
        if "자회사의주요경영사항" in name_clean:
            return self._parse_subsidiary_html(raw_html, report_name)

        # ── 7. 일반 주식소각결정 전용 파서
        if "주식소각결정" in name_clean:
            return self._parse_share_retirement_normal(raw_html)

        # ── 8. 일반 유상증자결정 전용 파서
        if "유상증자결정" in name_clean:
            return self._parse_capital_increase_normal(raw_html)

        # ── 9. 일반 감자결정 전용 파서
        if "감자결정" in name_clean:
            return self._parse_capital_reduction_normal(raw_html)

        # ── 10. 중대재해 전용 파서
        if "중대재해" in name_clean:
            return self._parse_disaster_html(raw_html)

        # ── 11. 그 외 비정형 공시 → 표 추출
        return self.extract_tables_from_html(raw_html)
