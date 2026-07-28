import os
from pathlib import Path
from dotenv import load_dotenv

# 프로젝트 루트 경로
ROOT_DIR = Path(__file__).resolve().parent.parent

# .env 파일 로드
env_path = ROOT_DIR / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    load_dotenv()

# API Keys
DART_API_KEY = os.getenv("DART_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Supabase Config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# Telegram API Config
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") or os.getenv("telegram_chat_id")

def validate_config():
    """설정값 유효성 검사"""
    missing = []
    if not DART_API_KEY or DART_API_KEY == "your_dart_api_key_here":
        missing.append("DART_API_KEY")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "your_gemini_api_key_here":
        missing.append("GEMINI_API_KEY")
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "your_telegram_bot_token_here":
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "your_telegram_chat_id_here":
        missing.append("TELEGRAM_CHAT_ID")
    if not SUPABASE_URL or SUPABASE_URL == "your_supabase_url_here":
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY or SUPABASE_KEY == "your_supabase_key_here":
        missing.append("SUPABASE_KEY")
        
    if missing:
        print(f"⚠️ 경고: 다음 환경 변수가 설정되지 않았거나 기본값입니다: {', '.join(missing)}")
        print("💡 .env 파일을 열고 실제 발급받은 API 키 및 접속 정보로 업데이트해 주세요.")
        return False
    return True

