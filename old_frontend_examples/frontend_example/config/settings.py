# config/settings.py - Configuration settings for the Streamlit application
import os
from pathlib import Path

# Django REST API Configuration
API_BASE_URL = os.getenv('DJANGO_API_URL', 'http://localhost:8000/api')

# Django Project Directory (matches settings.py PROJECT_DIR)
# This should match the PROJECT_DIR in your Django settings.py
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

# Media files configuration
MEDIA_ROOT = PROJECT_DIR / 'data'

# API Endpoints
ENDPOINTS = {
    'missions': f'{API_BASE_URL}/missions/',
    'sensors': f'{API_BASE_URL}/sensors/',
    'calibrations': f'{API_BASE_URL}/calibrations/',
    'media_assets': f'{API_BASE_URL}/media-assets/',
    'deployments': f'{API_BASE_URL}/deployments/',
    'nav_samples': f'{API_BASE_URL}/navsamples/',
    'frame_indices': f'{API_BASE_URL}/frame-indices/',
}

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

# Pagination settings
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# File upload settings
MAX_FILE_SIZE_MB = 200
ALLOWED_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']
ALLOWED_VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.wmv']

# UI Configuration
DEFAULT_DEPTH_RANGE = (0.0, 100.0)  # meters
DEFAULT_YAW_RANGE = (0.0, 360.0)    # degrees

# Error messages
ERROR_MESSAGES = {
    'connection_error': 'Cannot connect to Django backend. Please check if the server is running.',
    'api_error': 'API request failed. Please try again later.',
    'validation_error': 'Please check your input and try again.',
    'file_not_found': 'The requested file was not found.',
    'permission_error': 'You do not have permission to perform this action.',
}