# app.py - Main Streamlit Application for Underwater Rover Mission Management
import streamlit as st

# --- Imports ---
from config.settings import API_BASE_URL, PROJECT_DIR, MEDIA_ROOT
from utils.api_client import APIClient
from auth import check_auth


# --- Page Config ---
st.set_page_config(
    page_title="🌊 Underwater Rover Mission Control",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)


check_auth()

# --- Initialize API client ---
# This code will ONLY run if check_auth() passes
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)


def main_app():
    """Main application function"""

    st.sidebar.header(f"role: {st.session_state['role']}")

    # Main header
    st.title("🌊 Underwater Inspection Database Viewer")
    st.markdown("---")

    # Welcome message
    st.markdown("""
    ## Welcome to the Underwater Inspection Database Viewer

    This application allows you to manage underwater rover missions, sensors, calibrations, and media assets.
    Use the navigation sidebar to access different sections:

    - 🚀 **Missions**: View and manage rover missions
    - 🔧 **Sensors**: Configure sensors and add new ones
    - 📊 **Calibrations**: Manage sensor calibrations
    - 🎥 **Media Explorer**: Browse and filter media assets by location
    """)

    # Quick stats
    try:
        col1, col2, col3, col4, col5 = st.columns(5)

        with col1:
            missions = st.session_state.api_client.get_missions()
            st.metric("📋 Total Missions", len(missions) if missions else 0)

        with col2:
            sensors = st.session_state.api_client.get_sensors()
            st.metric("🔧 Total Sensors", len(sensors) if sensors else 0)

        with col3:
            calibrations = st.session_state.api_client.get_calibrations()
            st.metric("📊 Calibrations", len(calibrations) if calibrations else 0)

        with col4:
            media_response = st.session_state.api_client.get_media_assets(filters=None)
            media_count = 0
            if isinstance(media_response, dict):
                media_count = media_response.get('count', 0)
            elif isinstance(media_response, list):
                media_count = len(media_response)
            st.metric("🎥 Media Assets", media_count)

        with col5:
            rovers = st.session_state.api_client.get_rovers()
            st.metric("🚖 Rovers", len(rovers) if rovers else 0)

    except Exception as e:
        st.error(f"Error loading dashboard stats: {str(e)}")

    # System status
    st.markdown("---")
    st.markdown("### System Status")

    # Check API connection
    try:
        health_check = st.session_state.api_client.health_check()
        if health_check:
            st.success("✅ Connected to Django Backend")
        else:
            st.error("❌ Cannot connect to Django Backend")
    except Exception as e:
        st.error(f"❌ Django Backend Error: {str(e)}")

    # Show current configuration
    with st.expander("🔧 Configuration"):
        st.code(f"""
API Base URL: {API_BASE_URL}
Project Directory: {PROJECT_DIR}
Media Files Path: {MEDIA_ROOT}
        """)


# --- 6. UPDATE the main execution block ---
if __name__ == "__main__":
    # The 'if/else' is gone. If the script gets this far,
    # the user is authenticated.
    main_app()
