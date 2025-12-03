# 🌊 Underwater Rover Mission Control - Streamlit Frontend

A comprehensive Streamlit frontend application for managing underwater rover missions, sensors, calibrations, and media assets through a Django REST API backend.

## 📋 Features

### Core Functionality
- **Mission Management**: Create, view, and manage underwater rover missions
- **Sensor Configuration**: Add and configure sensors with specifications
- **Calibration Management**: Manage sensor calibrations with coefficients
- **Media Asset Explorer**: Browse and filter media assets by location and navigation data

### Advanced Features
- **Real-time API Integration**: Seamless communication with Django REST API
- **Dynamic Media Filtering**: Filter media by depth, yaw, location, and time
- **File Path Handling**: Proper handling of Django PROJECT_DIR media files
- **Navigation Data Integration**: Display media with associated navigation samples
- **Export Functionality**: Export filtered media metadata as CSV
- **Responsive Design**: Wide layout with sidebar navigation

## 🚀 Quick Start

### 1. Installation

```bash
# Clone or download the application files
cd streamlit_app

# Install dependencies
pip install -r requirements.txt
```

### 2. Configuration

Edit `config/settings.py` to match your Django setup:

```python
# Django REST API Configuration
API_BASE_URL = 'http://localhost:8000/api'  # Your Django API URL

# Django Project Directory (must match settings.py PROJECT_DIR)
PROJECT_DIR = Path('/path/to/your/django/project')  # Update this path
```

### 3. Environment Variables (Optional)

Create a `.env` file:

```bash
DJANGO_API_URL=http://localhost:8000/api
DJANGO_PROJECT_DIR=/path/to/your/django/project
```

### 4. Run the Application

```bash
streamlit run app.py
```

## 📁 Project Structure

```
streamlit_app/
├── app.py                    # Main application entry point
├── pages/
│   ├── 01_🚀_Missions.py    # Mission management page
│   ├── 02_🔧_Sensors.py     # Sensor configuration page
│   ├── 03_📊_Calibrations.py # Calibration management page
│   └── 04_🎥_Media_Explorer.py # Media asset explorer page
├── utils/
│   ├── __init__.py
│   ├── api_client.py        # Django REST API client
│   ├── file_utils.py        # Media file handling utilities
│   └── validators.py        # Form validation utilities
├── config/
│   ├── __init__.py
│   └── settings.py          # Application configuration
├── requirements.txt         # Python dependencies
└── README.md               # This file
```

## 🔧 Configuration Details

### API Endpoints

The application expects these Django REST API endpoints:

- `GET/POST /api/missions/` - Mission management
- `GET/POST /api/sensors/` - Sensor management
- `GET/POST /api/calibrations/` - Calibration management
- `GET /api/media-assets/` - Media asset retrieval
- `GET /api/media-assets/by_location/` - Location-based media filtering
- `GET /api/rovers/` - Rover hardware information
- `GET /api/deployments/` - Sensor deployments
- `GET /api/navsamples/` - Navigation samples

### Media File Handling

The application handles media files stored in your Django PROJECT_DIR:

1. **Django Configuration**: Media files are stored relative to `PROJECT_DIR/data/`
2. **Streamlit Configuration**: Update `PROJECT_DIR` in `config/settings.py`
3. **File Access**: The application converts relative paths to absolute paths for display

Example:
- Django MediaAsset.file_path: `"media/images/camera_001.jpg"`
- Resolved path: `PROJECT_DIR / "media/images/camera_001.jpg"`

### Navigation Data Filtering

The Media Explorer supports advanced filtering based on navigation sample data:

- **Depth Filtering**: Filter by depth range (meters)
- **Yaw Filtering**: Filter by yaw angle range (degrees)
- **Location Filtering**: Filter by mission location
- **Time Filtering**: Filter by time range (advanced)

## 🎯 Usage Guide

### 1. Mission Management

1. Navigate to the "🚀 Missions" page
2. View all missions in the table
3. Click on a mission to view details
4. Use the "Add Mission" tab to create new missions
5. Select rover, location, target type, and environmental conditions

### 2. Sensor Configuration

1. Navigate to the "🔧 Sensors" page
2. View all sensors and their specifications
3. Click on a sensor to view details and edit
4. Use the "Add Sensor" tab to create new sensors
5. Specify sensor type and JSON specifications

### 3. Calibration Management

1. Navigate to the "📊 Calibrations" page
2. View all calibrations and their status
3. Click on a calibration to view details and edit
4. Use the "Add Calibration" tab to create new calibrations
5. Select sensor and enter calibration coefficients as JSON

### 4. Media Asset Explorer

1. Navigate to the "🎥 Media Explorer" page
2. Use the sidebar to filter by:
   - Location (required)
   - Media type (image/video)
   - Depth range
   - Yaw angle range
3. Choose display mode:
   - **Grid View**: Visual grid of media items
   - **List View**: Compact list with navigation data
   - **Detailed View**: Full details with media preview
4. Click on media items to view full details
5. Export filtered metadata as CSV

## 🛠️ Customization

### Adding New Sensor Types

Edit `config/settings.py`:

```python
SENSOR_TYPES = [
    ('camera', 'camera'),
    ('compass', 'Compass'),
    ('imu', 'IMU'),
    ('pressure', 'Pressure'),
    ('sonar', 'sonar'),
    ('new_type', 'New Sensor Type'),  # Add new type
]
```

### Modifying Validation Rules

Edit `utils/validators.py` to add or modify validation functions:

```python
def validate_custom_field(value: str) -> Tuple[bool, str]:
    """Custom validation function"""
    if not value:
        return False, "Field is required"
    return True, ""
```

### Adding New API Endpoints

Edit `utils/api_client.py` to add new methods:

```python
def get_custom_data(self) -> List[Dict]:
    """Get custom data from API"""
    response = self._make_request('GET', '/custom-endpoint/')
    return response.get('results', [])
```

## 🔍 Troubleshooting

### Common Issues

1. **Cannot connect to Django backend**
   - Check if Django server is running
   - Verify `API_BASE_URL` in settings
   - Check firewall/network settings

2. **Media files not displaying**
   - Verify `PROJECT_DIR` path is correct
   - Check file permissions
   - Ensure media files exist at specified paths

3. **Validation errors**
   - Check form inputs match expected formats
   - Verify JSON format for specifications/coefficients
   - Check required fields are filled

4. **Import errors**
   - Ensure all dependencies are installed
   - Check Python path configuration
   - Verify file structure is correct

### Debug Mode

Add debug information to your Django API responses and check the browser console for detailed error messages.

## 📊 Performance Considerations

- **Caching**: API responses are cached in session state
- **Pagination**: Large datasets are paginated automatically
- **Media Loading**: Images are loaded on-demand for better performance
- **File Size Limits**: Configure appropriate file size limits for media uploads

## 🔒 Security Notes

- **API Authentication**: Add authentication headers as needed
- **Input Validation**: All forms include comprehensive validation
- **File Access**: Media files are accessed read-only
- **Error Handling**: Sensitive information is not exposed in error messages

## 🚀 Deployment

### Local Development
```bash
streamlit run app.py --server.port 8501
```

### Production Deployment
1. Set up proper environment variables
2. Configure reverse proxy (nginx/Apache)
3. Use process manager (systemd/supervisor)
4. Set up HTTPS certificates
5. Configure firewall rules

## 📄 License

This project is provided as-is for educational and development purposes.

## 🤝 Contributing

Feel free to submit issues and enhancement requests!

## 📞 Support

For support with this Streamlit frontend:
1. Check the troubleshooting section
2. Verify your Django API is working correctly
3. Check the browser console for JavaScript errors
4. Review the Streamlit logs for Python errors