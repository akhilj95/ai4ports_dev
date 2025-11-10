# pages/05_Media_Explorer.py
# Browse & filter underwater inspection media (images/videos) from Django backend,
# with frame-accurate seek, navigation metrics, and strict file validation.

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from auth import check_auth
from config.settings import API_BASE_URL, MEDIA_ROOT
from utils.api_client import APIClient


check_auth()

# Page setup
st.set_page_config(page_title="🎥 Media Explorer", layout="wide")

# API client init
if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)
api: APIClient = st.session_state.api_client


# -------------------------------------------------------------------
# File path validation helper
# -------------------------------------------------------------------
def validate_and_serve_media(file_path: str, media_root: str) -> str:
    """
    Convert relative media path to absolute, check for existence & readability.
    Raises FileNotFoundError if not found or not accessible.
    """
    if not file_path:
        raise FileNotFoundError("Empty media file path.")
    full_path = os.path.join(media_root, file_path.lstrip("/"))
    if os.path.exists(full_path) and os.access(full_path, os.R_OK):
        return full_path
    raise FileNotFoundError(f"Media file not found or not readable: {file_path}")


# -------------------------------------------------------------------
# Sidebar: filter controls
# -------------------------------------------------------------------
st.sidebar.header("🔍 Filter Media Assets")
with st.sidebar.form("media_filter_form", clear_on_submit=False):
    location = st.text_input("Location (Mission)", placeholder="Exact match")
    depth_min = st.number_input("Min Depth (m)", value=0.0, step=0.1)
    depth_max = st.number_input("Max Depth (m)", value=0.0, step=0.1)
    yaw_min = st.number_input("Min Yaw (°)", value=0.0, step=1.0)
    yaw_max = st.number_input("Max Yaw (°)", value=0.0, step=1.0)
    media_type = st.selectbox("Media Type", options=["", "image", "video"])
    start_after = st.date_input("Start After", value=None)
    start_before = st.date_input("Start Before", value=None)
    mission_id = st.text_input("Mission ID", placeholder="Exact match")
    sensor_id = st.text_input("Sensor ID", placeholder="Exact match")
    submitted = st.form_submit_button("Apply Filters")

filters: Dict[str, Any] = {}
if submitted:
    if location:
        filters["location"] = location
    if depth_min and depth_min > 0:
        filters["depth_min"] = depth_min
    if depth_max and depth_max > 0:
        filters["depth_max"] = depth_max
    if yaw_min and yaw_min > 0:
        filters["yaw_min"] = yaw_min
    if yaw_max and yaw_max > 0:
        filters["yaw_max"] = yaw_max
    if media_type:
        filters["media_type"] = media_type
    if start_after:
        filters["start_time__gte"] = datetime.combine(start_after, datetime.min.time()).isoformat()
    if start_before:
        filters["start_time__lte"] = datetime.combine(start_before, datetime.min.time()).isoformat()
    if mission_id:
        filters["deployment__mission"] = mission_id
    if sensor_id:
        filters["deployment__sensor"] = sensor_id


# -------------------------------------------------------------------
# Fetch assets from backend
# -------------------------------------------------------------------
try:
    media_assets: Any = api.get_media_assets(filters=filters if submitted else {})
    if isinstance(media_assets, dict) and "results" in media_assets:
        media_assets = media_assets["results"]
except Exception as e:
    st.error(f"Error fetching media assets: {e}")
    media_assets = []


# -------------------------------------------------------------------
# Display table
# -------------------------------------------------------------------
st.title("🎥 Media Explorer")
st.markdown("---")

if not media_assets:
    st.info("No media assets found. Adjust filters.")
    st.stop()

df = pd.DataFrame(media_assets)
display_columns = {
    "id": "ID",
    "media_type": "Type",
    "file_path": "File Path",
    "start_time": "Start Time",
    "end_time": "End Time",
    "deployment_details": "Deployment Details",
}
avail_cols = [c for c in display_columns.keys() if c in df.columns]
df_display = df[avail_cols].rename(columns=display_columns)
df_display["Select"] = False

edited_df = st.data_editor(df_display, use_container_width=True, key="media_table")
selected_rows = edited_df[edited_df["Select"]]
selected_assets: List[Dict[str, Any]] = [media_assets[i] for i in selected_rows.index] if not selected_rows.empty else []

# Sidebar stats
st.sidebar.metric("Total Media", len(media_assets))
st.sidebar.metric("Selected", len(selected_assets))


# -------------------------------------------------------------------
# Detailed previews
# -------------------------------------------------------------------
for asset in selected_assets:
    st.subheader(f"Media ID {asset['id']} - {asset['media_type'].capitalize()}")

    try:
        file_path = validate_and_serve_media(asset.get("file_path", ""), str(MEDIA_ROOT))
    except FileNotFoundError as e:
        st.error(str(e))
        continue

    # IMAGE
    if asset["media_type"] == "image":
        st.image(file_path, caption=f"Image Asset {asset['id']}", use_container_width=True)

    # VIDEO
    elif asset["media_type"] == "video":
        # Video length and frames
        try:
            start_dt = datetime.fromisoformat(asset["start_time"].replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(asset["end_time"].replace("Z", "+00:00"))
            duration = (end_dt - start_dt).total_seconds()
        except Exception:
            duration = 0

        fps: float = float(asset.get("fps") or 25.0)
        total_frames = int(duration * fps) if duration > 0 else 0

        sel_frame = st.slider(
            f"Select Frame – Media {asset['id']}",
            min_value=0,
            max_value=total_frames if total_frames > 0 else 0,
            value=0,
            step=1,
            format="%d",
        )
        # Build the full, absolute path
        full_media_path = str(MEDIA_ROOT / asset.get("file_path", ""))

        # --- DEBUGGING ---
        st.error(f"Looking for file at: {full_media_path}")
        st.info(f"Does file exist? {os.path.exists(full_media_path)}")
        # --- END DEBUGGING ---

        video_start_sec = sel_frame / fps if fps else 0.0
        st.video(file_path, start_time=video_start_sec)

        # Frame navigation data
        try:
            frame_data_resp: Any = api.get_frame_indices(
                media_asset_id=asset["id"], filters={"frame_number": sel_frame}
            )
            frames: List[Dict[str, Any]] = (
                frame_data_resp if isinstance(frame_data_resp, list)
                else frame_data_resp.get("results", [])
                if isinstance(frame_data_resp, dict) else []
            )

            matched_frame: Optional[Dict[str, Any]] = (
                frames[0] if frames and isinstance(frames[0], dict) else None
            )

            if matched_frame and isinstance(matched_frame, dict):
                nav: Optional[Dict[str, Any]] = matched_frame.get("nav_sample_details")
                if nav and isinstance(nav, dict):
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Depth (m)", f"{nav.get('depth_m', 'N/A'):.2f}" if nav.get("depth_m") is not None else "N/A")
                    c2.metric("Yaw (°)", f"{nav.get('yaw_deg', 'N/A'):.2f}" if nav.get("yaw_deg") is not None else "N/A")
                    c3.metric("Pitch (°)", f"{nav.get('pitch_deg', 'N/A'):.2f}" if nav.get("pitch_deg") is not None else "N/A")
                    c4.metric("Roll (°)", f"{nav.get('roll_deg', 'N/A'):.2f}" if nav.get("roll_deg") is not None else "N/A")
                else:
                    st.info("No navigation data for this frame.")
            else:
                st.info("No frame index data available for this media.")
        except Exception as e:
            st.warning(f"Frame navigation fetch error: {e}")

    # Deployment details
    dep = asset.get("deployment_details", {})
    st.markdown(f"**Mission Location:** {dep.get('mission_location', 'N/A')}")
    st.markdown(f"**Sensor:** {dep.get('sensor_name', 'N/A')} ({dep.get('sensor_type', 'N/A')})")
    st.markdown(f"**Time Range:** {asset.get('start_time')} → {asset.get('end_time', 'N/A')}")
    st.markdown(f"**File Path:** {file_path}")
    st.markdown("---")
