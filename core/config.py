"""Project settings; the optional root .env never overrides existing environment variables."""

from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{ROOT / 'data.db'}")
API_KEY = os.getenv("CONTENTPILOT_API_KEY", "")
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "local").lower()
LMSTUDIO_API_BASE = os.getenv("LMSTUDIO_API_BASE", "http://127.0.0.1:1234/v1").rstrip(
    "/"
)
LMSTUDIO_API_KEY = os.getenv("LMSTUDIO_API_KEY", "")
LMSTUDIO_MODEL = os.getenv("LMSTUDIO_MODEL", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-7B-Instruct")
MODEL_TIMEOUT = float(os.getenv("MODEL_TIMEOUT", "120"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "1800"))
WORDPRESS_API_URL = os.getenv("WORDPRESS_API_URL", "")
WORDPRESS_USERNAME = os.getenv("WORDPRESS_USERNAME", "")
WORDPRESS_PASSWORD = os.getenv("WORDPRESS_PASSWORD", "")
WORDPRESS_AUTO_PUBLISH = os.getenv("WORDPRESS_AUTO_PUBLISH", "false").lower() == "true"
WORDPRESS_DEFAULT_STATUS = os.getenv("WORDPRESS_DEFAULT_STATUS", "draft")
LOG_PATH = Path(
    os.getenv("CONTENTPILOT_LOG_PATH", str(ROOT / "logs" / "contentpilot.log"))
)
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() == "true"
