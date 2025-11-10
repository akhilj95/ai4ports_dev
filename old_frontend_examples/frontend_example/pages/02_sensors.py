# pages/02_🔧_Sensors.py - Sensor management page
import streamlit as st
import pandas as pd
import sys
from pathlib import Path
import json

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from utils.api_client import APIClient
from utils.validators import validate_form_and_display_errors
from config.settings import API_BASE_URL, SENSOR_TYPES

# Page configuration
st.set_page_config(page_title="🔧 Sensors", layout="wide")

# Initialize API client
if 'api_client' not in st.session_state:
    st.session_state.api_client = APIClient(API_BASE_URL)

def display_sensors_table(sensors):
    """Display sensors in a table format"""
    if not sensors:
        st.info("No sensors found")
        return None
    
    # Convert to DataFrame for better display
    df = pd.DataFrame(sensors)
    
    # Select and rename columns for display
    display_columns = {
        'id': 'ID',
        'name': 'Name',
        'sensor_type': 'Type',
        'specification': 'Specification'
    }
    
    # Filter and rename columns
    available_columns = [col for col in display_columns.keys() if col in df.columns]
    df_display = df[available_columns].copy()
    df_display = df_display.rename(columns=display_columns)
    
    # Format specification column
    if 'Specification' in df_display.columns:
        df_display['Specification'] = df_display['Specification'].apply(
            lambda x: json.dumps(x) if isinstance(x, dict) and x else "No specification"
        )
    
    # Add selection column
    df_display["Select"] = False
    
    # Display with selection using data_editor
    edited_df = st.data_editor(
        df_display,
        use_container_width=True,
        hide_index=True,
        key="sensors_table",
        column_config={
            "Select": st.column_config.CheckboxColumn(
                "Select",
                help="Select a sensor",
                default=False,
            )
        }
    )
    
    # Check for selected sensor
    selected_rows = edited_df[edited_df["Select"] == True]
    if not selected_rows.empty:
        selected_idx = selected_rows.index[0]
        selected_sensor = sensors[selected_idx]
        st.session_state.selected_sensor = selected_sensor
        return selected_sensor
    
    return None

def display_sensor_details(sensor):
    """Display detailed view of a selected sensor"""
    st.subheader(f"Sensor Details - {sensor.get('name', 'Unknown Sensor')}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.write(f"**ID:** {sensor.get('id', 'N/A')}")
        st.write(f"**Name:** {sensor.get('name', 'N/A')}")
        st.write(f"**Type:** {sensor.get('sensor_type', 'N/A').title()}")
    
    with col2:
        # Show specification
        spec = sensor.get('specification', {})
        if spec:
            st.write("**Specification:**")
            for key, value in spec.items():
                st.write(f"• {key}: {value}")
        else:
            st.write("**Specification:** No specification provided")
    
    # Show active calibration
    active_calibration = sensor.get('active_calibration')
    if active_calibration:
        st.subheader("Active Calibration")
        st.write(f"**Effective From:** {active_calibration.get('effective_from', 'N/A')}")
        
        coeffs = active_calibration.get('coefficients', {})
        if coeffs:
            st.write("**Coefficients:**")
            for key, value in coeffs.items():
                st.write(f"• {key}: {value}")
        else:
            st.write("**Coefficients:** No coefficients provided")
    else:
        st.info("No active calibration found for this sensor")

def create_sensor_form():
    """Create form for adding/editing sensors"""
    st.subheader("Add New Sensor")
    
    with st.form("sensor_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            # Sensor name
            name = st.text_input("Sensor Name", placeholder="e.g., Primary camera")
            
            # Sensor type
            sensor_type = st.selectbox(
                "Sensor Type",
                options=[choice[0] for choice in SENSOR_TYPES],
                format_func=lambda x: next(choice[1] for choice in SENSOR_TYPES if choice[0] == x)
            )
        
        with col2:
            # Specification (JSON)
            st.write("**Specification (JSON format):**")
            spec_text = st.text_area(
                "Specification",
                placeholder='{"resolution": "1920x1080", "fps": 30}',
                height=100,
                label_visibility="collapsed"
            )
        
        # Submit button
        submitted = st.form_submit_button("Create Sensor")
        
        if submitted:
            # Parse specification JSON
            specification = {}
            if spec_text.strip():
                try:
                    specification = json.loads(spec_text)
                except json.JSONDecodeError:
                    st.error("Invalid JSON format in specification")
                    return
            
            # Prepare sensor data
            sensor_data = {
                'name': name,
                'sensor_type': sensor_type,
                'specification': specification
            }
            
            # Validate form
            if validate_form_and_display_errors(sensor_data, 'sensor'):
                try:
                    # Create sensor
                    result = st.session_state.api_client.create_sensor(sensor_data)
                    if result:
                        st.success("Sensor created successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to create sensor")
                except Exception as e:
                    st.error(f"Error creating sensor: {str(e)}")

def edit_sensor_form(sensor):
    """Create form for editing an existing sensor"""
    st.subheader(f"Edit Sensor - {sensor.get('name', 'Unknown')}")
    
    with st.form("edit_sensor_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            # Sensor name
            name = st.text_input("Sensor Name", value=sensor.get('name', ''))
            
            # Sensor type
            current_type = sensor.get('sensor_type', '')
            type_index = next(
                (i for i, choice in enumerate(SENSOR_TYPES) if choice[0] == current_type), 
                0
            )
            sensor_type = st.selectbox(
                "Sensor Type",
                options=[choice[0] for choice in SENSOR_TYPES],
                format_func=lambda x: next(choice[1] for choice in SENSOR_TYPES if choice[0] == x),
                index=type_index
            )
        
        with col2:
            # Specification (JSON)
            st.write("**Specification (JSON format):**")
            current_spec = sensor.get('specification', {})
            spec_text = st.text_area(
                "Specification",
                value=json.dumps(current_spec, indent=2) if current_spec else "",
                height=100,
                label_visibility="collapsed"
            )
        
        # Submit button
        col1, col2 = st.columns(2)
        with col1:
            submitted = st.form_submit_button("Update Sensor")
        with col2:
            delete_clicked = st.form_submit_button("Delete Sensor", type="secondary")
        
        if submitted:
            # Parse specification JSON
            specification = {}
            if spec_text.strip():
                try:
                    specification = json.loads(spec_text)
                except json.JSONDecodeError:
                    st.error("Invalid JSON format in specification")
                    return
            
            # Prepare sensor data
            sensor_data = {
                'name': name,
                'sensor_type': sensor_type,
                'specification': specification
            }
            
            # Validate form
            if validate_form_and_display_errors(sensor_data, 'sensor'):
                try:
                    # Update sensor
                    result = st.session_state.api_client.update_sensor(sensor['id'], sensor_data)
                    if result:
                        st.success("Sensor updated successfully!")
                        st.rerun()
                    else:
                        st.error("Failed to update sensor")
                except Exception as e:
                    st.error(f"Error updating sensor: {str(e)}")
        
        if delete_clicked:
            # Use session state for confirmation instead of st.confirm
            if 'confirm_delete_sensor' not in st.session_state:
                st.session_state.confirm_delete_sensor = False
            
            if not st.session_state.confirm_delete_sensor:
                st.warning("Are you sure you want to delete this sensor?")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Yes, Delete", key="confirm_delete_sensor_btn"):
                        st.session_state.confirm_delete_sensor = True
                        st.rerun()
                with col2:
                    if st.button("Cancel", key="cancel_delete_sensor_btn"):
                        st.session_state.confirm_delete_sensor = False
                        st.rerun()
            else:
                try:
                    success = st.session_state.api_client.delete_sensor(sensor['id'])
                    if success:
                        st.success("Sensor deleted successfully!")
                        st.session_state.selected_sensor = None
                        st.session_state.confirm_delete_sensor = False
                        st.rerun()
                    else:
                        st.error("Failed to delete sensor")
                        st.session_state.confirm_delete_sensor = False
                except Exception as e:
                    st.error(f"Error deleting sensor: {str(e)}")
                    st.session_state.confirm_delete_sensor = False

def main():
    """Main function for the sensors page"""
    st.title("🔧 Sensor Management")
    st.markdown("---")
    
    # Create tabs
    tab1, tab2 = st.tabs(["📋 View Sensors", "➕ Add Sensor"])
    
    with tab1:
        st.header("All Sensors")
        
        # Load sensors
        try:
            sensors = st.session_state.api_client.get_sensors()
            
            if sensors:
                # Display sensors table
                selected_sensor = display_sensors_table(sensors)
                
                # Display sensor details if selected
                if selected_sensor or st.session_state.get('selected_sensor'):
                    sensor_to_show = selected_sensor or st.session_state.get('selected_sensor')
                    st.markdown("---")
                    display_sensor_details(sensor_to_show)
                    
                    # Show edit form
                    st.markdown("---")
                    edit_sensor_form(sensor_to_show)
                
                # Show summary statistics
                st.sidebar.header("Sensor Statistics")
                
                # Count by sensor type
                type_counts = {}
                for sensor in sensors:
                    sensor_type = sensor.get('sensor_type', 'Unknown')
                    type_counts[sensor_type] = type_counts.get(sensor_type, 0) + 1
                
                for sensor_type, count in type_counts.items():
                    st.sidebar.metric(f"{sensor_type.title()} Sensors", count)
                
                # Show total count
                st.sidebar.metric("Total Sensors", len(sensors))
                
            else:
                st.info("No sensors found. Add your first sensor using the 'Add Sensor' tab.")
                
        except Exception as e:
            st.error(f"Error loading sensors: {str(e)}")
    
    with tab2:
        create_sensor_form()
    
    # Refresh button
    if st.button("🔄 Refresh Data"):
        st.rerun()

if __name__ == "__main__":
    main()
