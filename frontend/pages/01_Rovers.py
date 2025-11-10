# pages/01_Rovers.py - Rovers management page
import streamlit as st
import pandas as pd
from auth import check_auth

from utils.api_client import APIClient
from config.settings import API_BASE_URL


check_auth()

# Page Configuration
st.set_page_config(page_title="🚖 Rovers", layout="wide")

# API client setup
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)

def display_rovers_table(rovers):
    """Display rover hardware in a table format"""
    if not rovers:
        st.info("No rovers found")
        return

    df = pd.DataFrame(rovers)
    display_columns = {
        'id': 'ID',
        'name': 'Name',
        'effective_from': 'Active From',
        'active': 'Active',
        'hardware_config': 'Hardware Config',
    }

    # Filter and rename columns for display
    available_columns = [col for col in display_columns.keys() if col in df.columns]
    df_display = df[available_columns].copy()
    df_display = df_display.rename(columns=display_columns)
    df_display["Select"] = False
    edited_df = st.data_editor(df_display, use_container_width=True, key="rover_table")

    selected_rows = edited_df[edited_df["Select"] == True]
    if not selected_rows.empty:
        selected_indices = selected_rows.index.tolist()
        selected_rovers = [rovers[i] for i in selected_indices]
        st.session_state.selected_rovers = selected_rovers
        return selected_rovers
    else:
        st.session_state.selected_rovers = []
        return []

def display_rover_details(rover):
    """Detailed view for a single rover hardware entry"""
    st.subheader(f"Rover Details - {rover.get('name', 'Unnamed')}")
    st.write(f"**ID:** {rover.get('id', 'N/A')}")
    st.write(f"**Name:** {rover.get('name', 'N/A')}")
    st.write(f"**Active:** {'Yes' if rover.get('active') else 'No'}")
    st.write(f"**Active From:** {rover.get('effective_from', 'N/A')}")
    config = rover.get('hardware_config', {})
    st.write("**Hardware Config:**")
    st.json(config)

def main():
    st.title("🚖 Rover Hardware Viewer")
    st.markdown("---")
    tab1, tab2 = st.tabs(["📋 View Rovers", "➕ Add Rover"])

    with tab1:
        st.header("All Rover Hardware")
        try:
            rovers = st.session_state.api_client.get_rovers()
            if rovers:
                selected_rovers = display_rovers_table(rovers)
                if selected_rovers or st.session_state.get('selected_rovers'):
                    to_show = selected_rovers or st.session_state.get('selected_rovers') or []
                    st.markdown("---")
                    for rover in to_show:
                        display_rover_details(rover)
                        st.markdown("---")
                # Display simple stats in sidebar
                st.sidebar.header("Rover Stats")
                st.sidebar.metric("Total Rovers", len(rovers))
                actives = sum(1 for r in rovers if r.get('active'))
                st.sidebar.metric("Active", actives)
            else:
                st.info("No rovers found. Add your first rover using the 'Add Rover' tab.")
        except Exception as e:
            st.error(f"Error loading rovers: {str(e)}")
    with tab2:
        st.info("Rover creation not yet implemented.")

    if st.button("🔄 Refresh Data"):
        st.rerun()

if __name__ == "__main__":
    main()