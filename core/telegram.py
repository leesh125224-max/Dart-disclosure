import time
import requests
import html
from typing import List

class TelegramClient:
    def __init__(self, token: str, chat_id: str):
        if not token or not chat_id:
            raise ValueError("Telegram Bot Token과 Chat ID가 설정되지 않았습니다.")
        self.token = token
        # 공백 제거 및 문자열 변환
        self.chat_id = str(chat_id).strip()
        self.send_url = f"https://api.telegram.org/bot{token.strip()}/sendMessage"

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """텔레그램으로 단일 메시지를 전송합니다."""
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        try:
            res = requests.post(self.send_url, json=payload, timeout=10)
            res_json = res.json()
            if res.status_code == 200 and res_json.get("ok"):
                return True
            else:
                # HTML 모드에서 태그 에러 등으로 실패한 경우, plain text로 변경하여 재시도
                if parse_mode == "HTML":
                    print(f"⚠️ Telegram HTML 전송 실패 ({res_json.get('description')}). 일반 텍스트로 재시도합니다.")
                    # HTML 태그를 제거(이스케이프)하고 전송
                    plain_text = html.escape(text)
                    return self.send_message(plain_text, parse_mode="Markdown")
                
                print(f"❌ Telegram 전송 실패: {res_json.get('description')} (코드: {res.status_code})")
                return False
        except Exception as e:
            print(f"❌ Telegram 전송 중 예외 발생: {type(e).__name__}")
            return False

    def send_large_message(self, text: str, parse_mode: str = "HTML") -> List[bool]:
        """텔레그램 메시지 길이 제한(4096자)을 고려하여 텍스트를 나누어 전송합니다."""
        MAX_LEN = 4000  # 여유 공간 확보
        
        # 줄 단위로 나누어 안전하게 분할
        lines = text.split("\n")
        chunks = []
        current_chunk = []
        current_len = 0
        
        for line in lines:
            # 한 줄이 이미 4000자를 넘는 극단적인 경우 강제 분할
            if len(line) > MAX_LEN:
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                    current_chunk = []
                    current_len = 0
                # 4000자 단위로 토막 내서 추가
                for i in range(0, len(line), MAX_LEN):
                    chunks.append(line[i:i+MAX_LEN])
                continue
                
            if current_len + len(line) + 1 > MAX_LEN:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = len(line)
            else:
                current_chunk.append(line)
                current_len += len(line) + 1
                
        if current_chunk:
            chunks.append("\n".join(current_chunk))
            
        results = []
        for idx, chunk in enumerate(chunks, 1):
            if len(chunks) > 1:
                header = f"<b>[공시 요약 파트 {idx}/{len(chunks)}]</b>\n" if parse_mode == "HTML" else f"*[공시 요약 파트 {idx}/{len(chunks)}]*\n"
                chunk = header + chunk
                
            success = self.send_message(chunk, parse_mode=parse_mode)
            results.append(success)
            
            # API Rate limit 방지를 위해 메시지 간 0.5초 대기
            if len(chunks) > 1:
                time.sleep(0.5)
                
        return results
