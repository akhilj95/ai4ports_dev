# pages/03_Missions.py - Missions management page
import streamlit as st
import pandas as pd
from auth import check_auth
from pathlib import Path
from datetime import datetime, timezone
import json

from utils.api_client import APIClient
from config.settings import API_BASE_URL, TARGET_TYPES, LEVEL_CHOICES


check_auth()

# Page configuration
st.set_page_config(page_title="🚀 Missions", layout="wide")

# Initialize API client
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)

def display_missions_table(missions):
    """Display missions in a table format"""
    if not missions:
        st.info("No missions found")
        return
    
    # Convert to DataFrame for better display
    df = pd.DataFrame(missions)
    
    # Select and rename columns for display
    display_columns = {
        'id': 'ID',
        'location': 'Location',
        'target_type': 'Target Type',
        'start_time': 'Start Time',
        'end_time': 'End Time',
        'max_depth': 'Max Depth (m)',
        'visibility': 'Visibility',
        'cloud_cover': 'Cloud Cover',
        'tide_level': 'Tide Level'
    }
    
    # Filter and rename columns
    available_columns = [col for col in display_columns.keys() if col in df.columns]
    df_display = df[available_columns].copy()
    df_display = df_display.rename(columns=display_columns)
    
    # Format datetime columns
    for col in ['Start Time', 'End Time']:
        if col in df_display.columns:
            df_display[col] = pd.to_datetime(df_display[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
    
    # Add a manual selection column
    df_display["Select"] = False
    edited_df = st.data_editor(df_display, use_container_width=True, key="mission_table")

    # Get selected missions based on checkbox
    selected_rows = edited_df[edited_df["Select"] == True]
    
    if not selected_rows.empty:
        selected_indices = selected_rows.index.tolist()
        selected_missions = [missions[i] for i in selected_indices]
        st.session_state.selected_missions = selected_missions
        return selected_missions
    else:
        # Clear previous selections if nothing is selected
        st.session_state.selected_missions = []
        return []

    return None

def display_mission_details(mission):
    """Display detailed view of a selected mission"""
    st.subheader(f"Mission Details - {mission.get('location', 'Unknown Location')}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**ID:** {mission.get('id', 'N/A')}")
        st.write(f"**Location:** {mission.get('location', 'N/A')}")
        st.write(f"**Target Type:** {mission.get('target_type', 'N/A').title()}")
        st.write(f"**Start Time:** {mission.get('start_time', 'N/A')}")
        st.write(f"**End Time:** {mission.get('end_time', 'N/A') or 'Ongoing'}")
    
    with col2:
        st.write(f"**Max Depth:** {mission.get('max_depth', 'N/A')} m")
        st.write(f"**Visibility:** {mission.get('visibility', 'N/A').title()}")
        st.write(f"**Cloud Cover:** {mission.get('cloud_cover', 'N/A').title()}")
        st.write(f"**Tide Level:** {mission.get('tide_level', 'N/A').title()}")
    
    if mission.get('notes'):
        st.write(f"**Notes:** {mission.get('notes')}")
    
    # Show rover information
    rover_info = mission.get('rover')
    if rover_info:
        st.subheader("Rover Information")
        if isinstance(rover_info, dict):
            st.write(f"**Rover:** {rover_info.get('name', 'N/A')}")
            st.write(f"**Hardware Config:** {rover_info.get('hardware_config', 'N/A')}")
        else:
            st.write(f"**Rover ID:** {rover_info}")

def create_mission_form():
    """Create form for adding/editing missions"""
    st.subheader("Add New Mission")

def main():
    """Main function for the missions page"""
    st.title("🚀 Mission Management")
    st.markdown("---")
    
    # Create tabs
    tab1, tab2 = st.tabs(["📋 View Missions", "➕ Add Mission"])
    
    with tab1:
        st.header("All Missions")
        
        # Load missions
        try:
            missions = st.session_state.api_client.get_missions()
            
            if missions:
                # Display missions table
                selected_missions = display_missions_table(missions)

                # Display mission details for all selected missions
                if selected_missions or st.session_state.get('selected_missions'):
                    missions_to_show = selected_missions or st.session_state.get('selected_missions') or []
                    st.markdown("---")
                    for mission in missions_to_show:
                        display_mission_details(mission)
                        st.markdown("---")
                
                # Show summary statistics
                st.sidebar.header("Mission Statistics")
                
                # Count by target type
                target_counts = {}
                for mission in missions:
                    target_type = mission.get('target_type', 'Unknown')
                    target_counts[target_type] = target_counts.get(target_type, 0) + 1
                
                for target_type, count in target_counts.items():
                    st.sidebar.metric(f"{target_type.title()} Missions", count)
                
                # Show locations
                locations = list(set(mission.get('location', 'Unknown') for mission in missions))
                st.sidebar.write(f"**Locations:** {len(locations)}")
                for location in sorted(locations):
                    st.sidebar.write(f"• {location}")
                
            else:
                st.info("No missions found. Add your first mission using the 'Add Mission' tab.")
                
        except Exception as e:
            st.error(f"Error loading missions: {str(e)}")
    
    with tab2:
        st.info("Mission creation not yet implemented.")
        # create_mission_form()
    
    # Refresh button
    if st.button("🔄 Refresh Data"):
        st.rerun()

if __name__ == "__main__":
    main()