# pages/04_Deployments.py - Sensor Deployments management page
import streamlit as st
import pandas as pd
from auth import check_auth
from utils.api_client import APIClient
from config.settings import API_BASE_URL


check_auth()

st.set_page_config(page_title="📦 Deployments", layout="wide")

# Initialize API client if not present
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)

def get_sensor_name(deployment):
    """Return the sensor name, fallback to ID if not available."""
    sensor = deployment.get("sensor")
    # Sensor may be a nested obj or just id; display nicely if possible
    if isinstance(sensor, dict):
        return sensor.get("name", f"ID:{sensor.get('id', '')}")
    return f"ID:{sensor}"

def get_mission_loc(deployment):
    """Return the mission location or ID."""
    mission = deployment.get("mission")
    if isinstance(mission, dict):
        return mission.get("location", f"ID:{mission.get('id', '')}")
    return f"ID:{mission}"

def display_deployments_table(deployments):
    """Display deployments as a selectable table."""
    if not deployments:
        st.info("No deployments found")
        return
    df = pd.DataFrame(deployments)
    # Add readable sensor and mission fields if not present
    df["Sensor"] = df.apply(get_sensor_name, axis=1)
    df["Mission Location"] = df.apply(get_mission_loc, axis=1)

    display_columns = {
        "id": "ID",
        "Sensor": "Sensor",
        "Mission Location": "Mission Location",
        "position": "Position",
        "instance": "Instance",
    }
    available_columns = [col for col in display_columns.keys() if col in df.columns]
    df_display = df[available_columns].copy()
    df_display = df_display.rename(columns=display_columns)
    df_display["Select"] = False

    edited_df = st.data_editor(df_display, use_container_width=True, key="deps_table")
    selected_rows = edited_df[edited_df["Select"] == True]
    if not selected_rows.empty:
        selected_indices = selected_rows.index.tolist()
        selected_deps = [deployments[i] for i in selected_indices]
        st.session_state.selected_deps = selected_deps
        return selected_deps
    else:
        st.session_state.selected_deps = []
        return []

def display_deployment_details(deployment):
    st.subheader(f"Deployment Details – ID {deployment.get('id', 'N/A')}")
    col1, col2 = st.columns(2)
    with col1:
        st.write(f"**Sensor:** {get_sensor_name(deployment)}")
        st.write(f"**Mission:** {get_mission_loc(deployment)}")
        st.write(f"**Position:** {deployment.get('position', 'N/A')}")
        st.write(f"**Instance:** {deployment.get('instance', 'N/A')}")
    with col2:
        # Calibration summary if data included
        calibration = deployment.get("calibration")
        st.write("**Calibration:**")
        if calibration:
            st.json(calibration)
        else:
            st.info("No calibration linked")
        if deployment.get("latest_coefficients"):
            st.write("**Calibration Coefficients:**")
            st.json(deployment["latest_coefficients"])

def main():
    st.title("📦 Sensor Deployments")
    st.markdown("---")
    tab1, tab2 = st.tabs(["📋 View Deployments", "➕ Add Deployment"])
    with tab1:
        st.header("All Sensor Deployments")
        try:
            # Fetch deployments using the API client (implement if missing)
            deployments = st.session_state.api_client._make_request("GET", "/deployments/")
            deployments = deployments.get("results", []) if "results" in deployments else deployments
            if deployments:
                selected_deps = display_deployments_table(deployments)
                if selected_deps or st.session_state.get('selected_deps'):
                    to_show = selected_deps or st.session_state.get('selected_deps') or []
                    st.markdown("---")
                    for dep in to_show:
                        display_deployment_details(dep)
                        st.markdown("---")
                # Sidebar statistics
                st.sidebar.header("Deployment Stats")
                st.sidebar.metric("Total Deployments", len(deployments))
                position_counts = df = pd.DataFrame(deployments)["position"].value_counts()
                for pos, count in position_counts.items():
                    st.sidebar.metric(f"{pos}", count)
            else:
                st.info("No deployments found. Add your first deployment using the 'Add Deployment' tab.")
        except Exception as e:
            st.error(f"Error loading deployments: {str(e)}")
    with tab2:
        st.info("Deployment creation not yet implemented.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

if __name__ == "__main__":
    main()
