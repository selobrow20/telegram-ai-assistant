import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Load environment variables
load_dotenv(BASE_DIR / ".env")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_USER_ID = os.getenv("ADMIN_USER_ID", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite").strip()
VOICE_REPLY_ENABLED = os.getenv("VOICE_REPLY_ENABLED", "true").lower() in ("true", "1", "yes")
TTS_VOICE = os.getenv("TTS_VOICE", "id-ID-GadisNeural").strip()  # id-ID-GadisNeural (suara cewek natural & ramah)
TTS_RATE = os.getenv("TTS_RATE", "+8%").strip()  # Kecepatan lebih hidup (+8%)
TTS_PITCH = os.getenv("TTS_PITCH", "+2Hz").strip()  # Nada lebih cerah (+2Hz)
TTS_ENGINE = os.getenv("TTS_ENGINE", "edge-tts").strip()  # 'edge-tts' atau 'gemini'

DATABASE_PATH = DATA_DIR / "assistant.db"
