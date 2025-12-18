"""Application configuration."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Try to get secrets from Streamlit (for Streamlit Cloud)
def get_secret(key: str, default: str = None) -> str:
    """Get secret from Streamlit secrets or environment."""
    try:
        import streamlit as st
        return st.secrets.get(key, os.getenv(key, default))
    except:
        return os.getenv(key, default)

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
VENUES_DIR = DATA_DIR / "venues"
TEMPLATES_DIR = DATA_DIR / "templates"

# API Keys
OPENAI_API_KEY = get_secret("OPENAI_API_KEY")
REPLICATE_API_TOKEN = get_secret("REPLICATE_API_TOKEN")
MODAL_TOKEN_ID = get_secret("MODAL_TOKEN_ID")
MODAL_TOKEN_SECRET = get_secret("MODAL_TOKEN_SECRET")

# Render settings
DEFAULT_RENDER_WIDTH = 1920
DEFAULT_RENDER_HEIGHT = 1080
DEFAULT_RENDER_SAMPLES = 64  # Balance of quality and speed

# Cache settings
CACHE_ENABLED = True
CACHE_DIR = BASE_DIR / "cache" / "renders"
CACHE_POSITION_PRECISION = 0.5  # Round positions to 0.5m grid for caching
