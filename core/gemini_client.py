import requests
from typing import Optional

class GeminiClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Gemini API Key가 설정되지 않았습니다.")
        self.api_key = api_key
        # 비용 효율적이고 빠른 gemini-1.5-flash 모델 사용
        # API Key가 URL에 노출되는 보안 위협을 피하기 위해 URL 뒤에 ?key= 파라미터를 붙이지 않고 헤더로 전달합니다.
        self.url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

    def summarize_disclosure(self, corp_name: str, report_name: str, raw_html_or_text: str) -> str:
        """주요경영사항 공시 본문을 Gemini API를 통해 핵심 요약합니다."""
        # 텍스트가 너무 길면 잘라내어 API 오버헤드 방지 (15,000자 제한)
        text_truncated = raw_html_or_text[:15000]
        
        prompt = (
            f"회사명: {corp_name}\n"
            f"보고서명: {report_name}\n\n"
            f"위 기업의 '투자판단관련 주요경영사항' 공시 원문(HTML 또는 텍스트)이 아래에 제공됩니다.\n"
            f"투자자가 핵심을 한눈에 파악할 수 있도록 다음 규칙을 지켜 요약해 주세요:\n"
            f"1. 공시 목적, 계약/결정 내역, 금액, 일정 등 핵심 수치와 중요 사실을 명확히 요약에 담아주세요.\n"
            f"2. 전체 내용을 가독성이 좋은 한국어 개조식(3~5줄)으로 정리해 주세요.\n"
            f"3. 다른 인사말이나 부연설명 없이 요약 본문만 반환해 주세요.\n\n"
            f"--- 공시 원문 ---\n{text_truncated}"
        )

        # x-goog-api-key 헤더를 통해 API Key를 전달하여 로그 및 에러 트레이스상의 키 유출을 원천 방어합니다.
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }
        
        data = {
            "contents": [{
                "parts": [{
                    "text": prompt
                }]
            }]
        }

        try:
            # 30초 타임아웃
            response = requests.post(self.url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            res_json = response.json()
            
            # 응답 구조 파싱
            summary = res_json['candidates'][0]['content']['parts'][0]['text']
            return summary.strip()
        except requests.exceptions.HTTPError as e:
            # 예외 객체 전체를 출력하여 주소나 상세 정보가 로그에 남는 것을 원천적으로 차단합니다.
            status_code = e.response.status_code if e.response is not None else "알수없음"
            print(f"❌ Gemini API 오류 ({corp_name}): status={status_code}")
            return "⚠️ Gemini 요약에 실패했습니다. 상세 링크의 공시 원문을 확인해 주세요."
        except Exception as e:
            # 예외 객체 대신 예외의 클래스명만 출력하여 혹시 모를 내부 키 노출 가능성을 완벽히 격리합니다.
            print(f"❌ Gemini API 요약 중 오류 발생 ({corp_name}): {type(e).__name__}")
            return "⚠️ Gemini 요약에 실패했습니다. 상세 링크의 공시 원문을 확인해 주세요."
