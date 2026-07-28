from supabase import create_client, Client
from typing import List, Dict, Any

class SupabaseClient:
    def __init__(self, url: str, key: str):
        if not url or not key:
            raise ValueError("Supabase URL과 Key가 설정되지 않았습니다.")
        self.client: Client = create_client(url, key)
        self.table_name = "dart_announcements"

    def get_today_processed_rcept_nos(self, date_str: str) -> List[str]:
        """특정 날짜(YYYY-MM-DD)에 이미 처리 및 발송이 완료된 공시의 접수번호 목록을 조회합니다."""
        try:
            # rcept_dt 필드가 date_str과 일치하는 행들의 rcept_no 조회
            response = self.client.table(self.table_name).select("rcept_no").eq("rcept_dt", date_str).execute()
            
            # API 응답 데이터 파싱
            if response.data:
                return [row["rcept_no"] for row in response.data]
            return []
        except Exception as e:
            print(f"❌ Supabase 조회 오류 (날짜: {date_str}): {type(e).__name__}")
            return []

    def insert_announcement(self, data: Dict[str, Any]) -> bool:
        """새롭게 처리 완료된 공시 이력 데이터를 Supabase DB에 인서트합니다."""
        try:
            response = self.client.table(self.table_name).insert(data).execute()
            if response.data:
                print(f"💾 Supabase 저장 완료: {data.get('corp_name')} | {data.get('rcept_no')}")
                return True
            return False
        except Exception as e:
            print(f"❌ Supabase 저장 오류 (접수번호: {data.get('rcept_no')}): {type(e).__name__}")
            return False
