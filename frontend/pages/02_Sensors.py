# pages/02_Sensors.py - Sensors management page
import streamlit as st
import pandas as pd

from auth import check_auth
from utils.api_client import APIClient
from config.settings import API_BASE_URL, SENSOR_TYPES


check_auth()

st.set_page_config(page_title="🔧 Sensors", layout="wide")

# Initialize API client if not present
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)

def display_sensors_table(sensors):
    """Display the sensors table with selection support."""
    if not sensors:
        st.info("No sensors found")
        return

    df = pd.DataFrame(sensors)

    # Prepare display columns (ensure columns exist)
    display_columns = {
        'id': 'ID',
        'name': 'Name',
        'sensor_type': 'Type',
        'specification': 'Specification',
    }
    available_columns = [col for col in display_columns.keys() if col in df.columns]
    df_display = df[available_columns].copy().rename(columns=display_columns)

    # Optionally stringify specification
    if "Specification" in df_display.columns:
        df_display["Specification"] = df_display["Specification"].apply(lambda x: str(x) if x else "")
    
    df_display["Select"] = False
    edited_df = st.data_editor(df_display, use_container_width=True, key="sensors_table")
    selected_rows = edited_df[edited_df["Select"] == True]
    
    if not selected_rows.empty:
        # get the selected sensors by index
        selected_indices = selected_rows.index.tolist()
        selected_sensors = [sensors[i] for i in selected_indices]
        st.session_state.selected_sensors = selected_sensors
        return selected_sensors
    else:
        st.session_state.selected_sensors = []
        return []

def display_sensor_details(sensor):
    """Display detailed info, including active calibration."""
    st.subheader(f"Sensor Details – {sensor.get('name', 'Unnamed Sensor')}")

    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**ID:** {sensor.get('id', 'N/A')}")
        st.write(f"**Type:** {sensor.get('sensor_type', 'N/A').capitalize()}")
        st.write(f"**Specification:**")
        st.json(sensor.get('specification', {}))
    with col2:
        calib = sensor.get('active_calibration')
        st.write("**Active Calibration:**")
        if calib:
            st.json(calib)
        else:
            st.info("No active calibration")

def main():
    st.title("🔧 Sensor Management")
    st.markdown("---")
    tab1, tab2 = st.tabs(["📋 View Sensors", "➕ Add Sensor"])

    with tab1:
        st.header("All Sensors")
        try:
            sensors = st.session_state.api_client.get_sensors()
            if sensors:
                selected_sensors = display_sensors_table(sensors)
                if selected_sensors or st.session_state.get('selected_sensors'):
                    for sensor in selected_sensors or st.session_state.get('selected_sensors', []):
                        st.markdown("---")
                        display_sensor_details(sensor)
                        st.markdown("---")
                # Sidebar summary
                st.sidebar.header("Sensor Statistics")
                st.sidebar.metric("Total Sensors", len(sensors))
                # Count by sensor_type
                type_counts = {}
                for sensor in sensors:
                    t = sensor.get('sensor_type', 'unknown').capitalize()
                    type_counts[t] = type_counts.get(t, 0) + 1
                for typ, count in type_counts.items():
                    st.sidebar.metric(typ, count)
            else:
                st.info("No sensors found. Add your first sensor on the next tab.")
        except Exception as e:
            st.error(f"Error loading sensors: {str(e)}")

    with tab2:
        st.info("Sensor creation is not yet implemented.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

if __name__ == "__main__":
    main()
