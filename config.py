"""
QuizLive — Configuration
Loads settings from environment variables with sensible development defaults.
"""

import os
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded reliably regardless of working directory
_CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_CONFIG_DIR, ".env")
if os.path.isfile(_ENV_PATH):
    load_dotenv(_ENV_PATH)
load_dotenv()

def load_environment() -> None:
    """Explicitly load environment variables from .env file."""
    if os.path.isfile(_ENV_PATH):
        load_dotenv(_ENV_PATH)
    load_dotenv()


class Config:
    """Application configuration loaded from environment variables."""

    # Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "quizlive-demo-secret-key-2026")

    # Supabase Cloud
    _raw_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    if _raw_url.endswith("/rest/v1"):
        _raw_url = _raw_url[:-8].rstrip("/")
    SUPABASE_URL = _raw_url
    SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")  # anon / public key
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")  # service-role key

    # Demo Mode: activated if explicitly set, or automatically when Supabase URL is not configured
    DEMO_MODE = os.getenv("DEMO_MODE", "").lower() in ("true", "1", "yes") or not SUPABASE_URL

    # Public site URL (used for OAuth redirect)
    SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:5000")

    # Session
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Uploads (2 MB default maximum file size)
    DEFAULT_MAX_IMAGE_BYTES = 2097152
    MAX_IMAGE_SIZE = int(os.getenv("MAX_IMAGE_SIZE", str(DEFAULT_MAX_IMAGE_BYTES)))
    ALLOWED_IMAGE_MIME = frozenset({"image/jpeg", "image/png"})
