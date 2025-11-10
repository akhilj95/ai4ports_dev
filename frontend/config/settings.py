# config/settings.py - Configuration settings for the Streamlit application
import streamlit as st
from pathlib import Path

# Django REST API Configuration
API_BASE_URL = st.secrets.get("DJANGO_API_URL", "http://localhost:8000/api")

# Django Project Directory (matches settings.py PROJECT_DIR)
# This should match the PROJECT_DIR in your Django settings.py
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

# Media files configuration
# MEDIA_ROOT = PROJECT_DIR / 'data'
# TEMP FIX, TO BE CORRECTED
MEDIA_ROOT = PROJECT_DIR    # file path currently starts from project root instead of media_root
MEDIA_URL = "/media/"

# Media file validation settings
SUPPORTED_IMAGE_FORMATS = [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff"]
SUPPORTED_VIDEO_FORMATS = [".mp4", ".avi", ".mov", ".mkv", ".webm"]
MAX_FILE_SIZE_MB = 500

# Video playback settings
DEFAULT_VIDEO_FPS = 30
MAX_VIDEO_DURATION_SECONDS = 3600

# UI settings for media explorer
MEDIA_GRID_COLUMNS = 3
DEFAULT_PAGE_SIZE = 20

# Sensor type choices (matching Django model)
SENSOR_TYPES = [
    ('camera', 'camera'),
    ('compass', 'Compass'),
    ('imu', 'IMU'),
    ('pressure', 'Pressure'),
    ('sonar', 'sonar'),
]

# Mission target types (matching Django model)
TARGET_TYPES = [
    ('pillar', 'Pillar'),
    ('wall', 'Wall'),
]

# Level choices (matching Django model)
LEVEL_CHOICES = [
    ('low', 'Low'),
    ('medium', 'Medium'),
    ('high', 'High'),
]

# Media types (matching Django model)
MEDIA_TYPES = [
    ('image', 'Image'),
    ('video', 'Video'),
]
