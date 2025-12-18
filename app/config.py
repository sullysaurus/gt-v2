"""Application configuration."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
VENUES_DIR = DATA_DIR / "venues"
TEMPLATES_DIR = DATA_DIR / "templates"

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")

# Render settings
DEFAULT_RENDER_WIDTH = 1920
DEFAULT_RENDER_HEIGHT = 1080
DEFAULT_RENDER_SAMPLES = 64  # Balance of quality and speed

# Cache settings
CACHE_ENABLED = True
CACHE_DIR = BASE_DIR / "cache" / "renders"
CACHE_POSITION_PRECISION = 0.5  # Round positions to 0.5m grid for caching
