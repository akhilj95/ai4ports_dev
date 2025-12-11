import os
import streamlit as st
import pandas as pd
from datetime import datetime
from typing import Any, Dict, List, Optional

from auth import check_auth
from config.settings import API_BASE_URL, MEDIA_ROOT
from utils.api_client import APIClient

# --- Authentication & Setup ---
check_auth()
st.set_page_config(page_title="🎥 Media Explorer", layout="wide")

if "api_client" not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)
api: APIClient = st.session_state.api_client

# --- Helper Functions ---

def validate_and_serve_media(file_path: str, media_root: str) -> Optional[str]:
    """Resolve media path to absolute system path."""
    if not file_path:
        return None
    clean_path = file_path.lstrip("/")
    full_path = os.path.join(media_root, clean_path)
    if os.path.exists(full_path):
        return full_path
    return None

def format_duration(start_str, end_str):
    """Calculate duration string from ISO timestamps"""
    if not start_str: return ""
    try:
        s = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        if not end_str: return s.strftime("%H:%M:%S")
        e = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        seconds = int((e - s).total_seconds())
        return f"{seconds}s"
    except:
        return "N/A"

@st.cache_data(ttl=60)
def get_locations_list():
    try:
        locations = api.get_locations()
        if locations:
            return sorted([loc['name'] for loc in locations])
    except Exception:
        pass
    return []

# --- Main Application Logic ---

def main():
    st.title("🎥 Mission Media Browser")

    # Initialize State for tracking open lists
    if 'expanded_mission_id' not in st.session_state:
        st.session_state.expanded_mission_id = None

    # 1. Scope Selection
    loc_names = get_locations_list()
    c1, c2 = st.columns([1, 3])
    with c1:
        selected_loc_name = st.selectbox(
            "📍 Select Location", 
            options=["All Locations"] + loc_names
        )
    st.divider()

    # 2. Fetch Missions
    mission_params = {'ordering': '-start_time'}
    if selected_loc_name != "All Locations":
        mission_params['location_name'] = selected_loc_name

    with st.spinner("Loading missions..."):
        missions = api.get_missions(filters=mission_params)
    
    if not missions:
        st.info(f"No missions found for {selected_loc_name}.")
        return

    st.subheader(f"Missions ({len(missions)})")
    
    # 3. Iterate Missions
    for mission in missions:
        label = f"🚀 {mission['start_time'][:10]} | {mission.get('target_type', 'N/A').title()} | {mission.get('location', 'N/A')}"
        
        # KEY CHANGE 1: Maintain Expander State
        # If this mission was the last one interacted with, force it open.
        is_expanded = (st.session_state.expanded_mission_id == mission['id'])
        
        with st.expander(label, expanded=is_expanded):
            
            # Lazy Load Media
            # Note: If expanded=True, Streamlit runs this code immediately.
            mission_filter = {'deployment__mission': mission['id']}
            media_resp = api.get_media_assets(filters=mission_filter, page_size=50)
            assets = media_resp.get('results', []) if isinstance(media_resp, dict) else []
            
            if not assets:
                st.caption("No media found.")
            else:
                for asset in assets:
                    # Resolve Paths
                    thumb = validate_and_serve_media(asset.get('thumbnail_path'), str(MEDIA_ROOT))
                    
                    file_p = asset.get('file_path')
                    if asset['media_type'] == 'image_set':
                        file_p = asset.get('generated_video_path')
                    
                    play_path = validate_and_serve_media(file_p, str(MEDIA_ROOT))
                    
                    # Check if THIS specific asset is currently selected
                    is_playing = (st.session_state.get('selected_media_id') == asset['id'])

                    # Visual Highlight for playing item
                    if is_playing:
                        st.markdown(f"#### 🟢 Playing: {asset['media_type'].upper()} {asset['id']}")
                    
                    # Standard Row Layout
                    c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
                    
                    with c1:
                        if thumb: st.image(thumb)
                        else: st.markdown("📷")
                    
                    with c2:
                        st.caption(f"ID: {asset['id']} | {asset['media_type']}")
                        if asset.get('min_depth_m'):
                            st.caption(f"Depth: {asset['min_depth_m']:.1f}m - {asset['max_depth_m']:.1f}m")

                    with c3:
                        s_time = asset['start_time'].split("T")[1][:8]
                        dur = format_duration(asset['start_time'], asset.get('end_time'))
                        st.caption(f"Start: {s_time} | Dur: {dur}")
                    
                    with c4:
                        # KEY CHANGE 2: Update State inline without scrolling up
                        btn_label = "⏹ Close" if is_playing else "▶️ Play"
                        
                        if st.button(btn_label, key=f"btn_{asset['id']}", disabled=(play_path is None)):
                            if is_playing:
                                # Toggle OFF
                                st.session_state.selected_media_id = None
                            else:
                                # Toggle ON
                                st.session_state.selected_media_id = asset['id']
                                st.session_state.expanded_mission_id = mission['id'] # Lock expander open
                                st.session_state.playing_file_path = play_path
                                st.session_state.playing_media_type = asset['media_type']
                                st.session_state.playing_metadata = {
                                    "Start": asset['start_time'],
                                    "End": asset.get('end_time'),
                                    "FPS": asset.get('fps'),
                                    "min_depth": asset.get('min_depth_m'),
                                    "Sensor": asset.get('deployment_details', {}).get('sensor_name')
                                }
                            st.rerun()

                    # KEY CHANGE 3: Inline Player (Conditional Render)
                    if is_playing and play_path:
                        render_inline_player(asset['id'], play_path, st.session_state.playing_media_type, st.session_state.playing_metadata)

                    st.divider()

def render_inline_player(m_id, path, m_type, meta):
    """Renders the player directly inside the list item"""
    
    # Use a container to visually group the player
    with st.container(border=True):
        col_viz, col_data = st.columns([2, 1])
        
        # --- Visualization ---
        with col_viz:
            if m_type in ['video', 'image_set']:
                fps = float(meta.get("FPS") or 25.0)
                try:
                    s = datetime.fromisoformat(meta["Start"].replace("Z", "+00:00"))
                    e = datetime.fromisoformat(meta["End"].replace("Z", "+00:00"))
                    duration = (e - s).total_seconds()
                    total_frames = int(duration * fps)
                except:
                    total_frames = 100
                    
                selected_frame = st.slider(
                    "Scrub Timeline", 0, total_frames, 0, 1, key=f"scrub_{m_id}"
                )
                
                start_sec = selected_frame / fps
                st.video(path, start_time=start_sec)
                
            elif m_type == 'image':
                st.image(path, use_container_width=True)
                selected_frame = 0

        # --- Data ---
        with col_data:
            st.markdown("**Frame Data**")
            
            if m_type in ['video', 'image_set']:
                # Live Fetch frame data
                frame_data = api.get_frame_indices(
                    media_asset_id=m_id, 
                    filters={"frame_number": selected_frame}
                )
                
                results = frame_data.get('results', []) if isinstance(frame_data, dict) else frame_data
                current_nav = results[0].get('nav_sample_details') if results else None
                
                if current_nav:
                    st.metric("Depth", f"{current_nav.get('depth_m', 0):.2f}m")
                    st.metric("Yaw", f"{current_nav.get('yaw_deg', 0):.1f}°")
                    st.caption(f"Pitch: {current_nav.get('pitch_deg', 0):.1f}° | Roll: {current_nav.get('roll_deg', 0):.1f}°")
                else:
                    st.warning("No nav data linked")
            
            elif m_type == 'image':
                st.metric("Depth", f"{meta.get('min_depth', 0):.2f}m")

if __name__ == "__main__":
    main()