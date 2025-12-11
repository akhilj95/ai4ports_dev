# utils/api_client.py - Django REST API client for Streamlit application
import requests
import streamlit as st
from typing import Dict, List, Optional, Any, Union, cast

class APIClient:
    """Client for communicating with Django REST API"""
    
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

    def _make_request(self, method: str, endpoint: str, **kwargs) -> Union[Dict[str, Any], List[Any]]:
        """
        Make HTTP request with error handling and automatic auth injection.
        """
        # 1. Handle full URLs (for pagination) vs relative endpoints
        if endpoint.startswith("http"):
            url = endpoint
        else:
            url = f"{self.base_url}{endpoint}"
        
        # 2. Authentication Injection
        # Get existing headers or create new dict
        headers = kwargs.get('headers', {})
        
        # Retrieve token from session state (set in auth.py)
        token = st.session_state.get('token')
        if token:
            headers['Authorization'] = f'Bearer {token}'
            
        kwargs['headers'] = headers

        # 3. Execute Request
        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            
            # Return empty dict for 204 No Content, otherwise JSON
            return response.json() if response.content else {}
            
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to Django backend. Please check if the server is running.")
            return {}
        except requests.exceptions.HTTPError as e:
            # Handle specific HTTP errors without crashing
            if response.status_code == 400:
                st.error(f"Validation error: {response.text}")
            elif response.status_code == 401:
                st.warning("Session expired or unauthorized. Please log in again.")
            elif response.status_code == 403:
                st.error("You do not have permission to perform this action.")
            elif response.status_code == 404:
                # 404s are often expected (e.g. empty search), so we might not want to show an error
                # print(f"Resource not found: {url}") # Optional logging
                pass
            elif response.status_code == 500:
                st.error("Internal server error")
            else:
                st.error(f"HTTP error {response.status_code}: {response.text}")
            return {}
        except requests.exceptions.RequestException as e:
            st.error(f"Request failed: {str(e)}")
            return {}

    def get_all_pages(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """
        Helper to fetch ALL results from a paginated endpoint by automatically 
        following 'next' links. Essential for things like Frame Indices.
        """
        all_results = []
        current_params = params or {}
        
        # Initial request
        response = self._make_request('GET', endpoint, params=current_params)
        
        # Handle non-paginated responses (just a list)
        if isinstance(response, list):
            return cast(List[Dict[str, Any]], response)
            
        # Handle paginated responses (dict with 'results')
        if isinstance(response, dict):
            results = response.get('results', [])
            all_results.extend(results)
            
            # Loop while there is a 'next' URL
            next_url = response.get('next')
            while next_url:
                try:
                    # Request the next URL (it is absolute, so _make_request handles it)
                    response = self._make_request('GET', next_url)
                    
                    if isinstance(response, dict):
                        new_results = response.get('results', [])
                        all_results.extend(new_results)
                        next_url = response.get('next')
                    else:
                        break
                except Exception:
                    break
                    
        return cast(List[Dict[str, Any]], all_results)

    def health_check(self) -> bool:
        """
        Check if the Django backend is accessible.
        Uses a raw request to avoid triggering UI error messages.
        """
        try:
            # We use a raw requests.get here to bypass the st.error() calls in _make_request
            # We check /missions/ as a heartbeat
            url = f"{self.base_url}/missions/"
            response = requests.get(url, timeout=3)
            
            # 200 = OK, 401/403 = OK (Server is up, just protected)
            return response.status_code in [200, 401, 403]
        except:
            return False
    
    # ------------------------------------------------------------------
    # Core Data Methods
    # ------------------------------------------------------------------

    def get_rovers(self) -> List[Dict[str, Any]]:
        """Get all rover hardware"""
        response = self._make_request('GET', '/rovers/')
        return cast(List[Dict[str, Any]], response.get('results', []) if isinstance(response, dict) and 'results' in response else response if isinstance(response, list) else [])

    def get_missions(self, filters: Optional[Dict] = None) -> List[Dict[str, Any]]:
        """Get missions with optional filtering"""
        response = self._make_request('GET', '/missions/', params=filters)
        return cast(List[Dict[str, Any]], response.get('results', []) if isinstance(response, dict) and 'results' in response else response if isinstance(response, list) else [])
    
    def get_mission(self, mission_id: int) -> Dict[str, Any]:
        """Get a specific mission details"""
        response = self._make_request('GET', f'/missions/{mission_id}/')
        return cast(Dict[str, Any], response)

    def get_locations(self) -> List[Dict[str, Any]]:
        """Get all locations (useful for dropdowns)"""
        # Uses pagination helper to ensure we get ALL locations for the dropdown
        return self.get_all_pages('/locations/')

    def get_sensors(self) -> List[Dict[str, Any]]:
        response = self._make_request('GET', '/sensors/')
        return cast(List[Dict[str, Any]], response.get('results', []) if isinstance(response, dict) and 'results' in response else response if isinstance(response, list) else [])
    
    def get_sensor(self, sensor_id: int) -> Dict[str, Any]:
        response = self._make_request('GET', f'/sensors/{sensor_id}/')
        return cast(Dict[str, Any], response)
    
    def get_deployments(self) -> List[Dict[str, Any]]:
        response = self._make_request('GET', '/deployments/')
        return cast(List[Dict[str, Any]], response.get('results', []) if isinstance(response, dict) and 'results' in response else response if isinstance(response, list) else [])

    def get_calibrations(self) -> List[Dict[str, Any]]:
        response = self._make_request('GET', '/calibrations/')
        return cast(List[Dict[str, Any]], response.get('results', []) if isinstance(response, dict) and 'results' in response else response if isinstance(response, list) else [])
    
    def get_calibration(self, calibration_id: int) -> Dict[str, Any]:
        response = self._make_request('GET', f'/calibrations/{calibration_id}/')
        return cast(Dict[str, Any], response)
    

    # ------------------------------------------------------------------
    # Media & Frame Sync Methods
    # ------------------------------------------------------------------

    def get_media_assets(self, filters=None, page=None, page_size=None) -> Dict[str, Any]:
        """
        Get media assets with optional filtering and pagination
        """
        params = {}

        # Clean filters
        if filters:
            for key, value in filters.items():
                if value is not None and value != "":
                    params[key] = value
        
        # Add pagination
        if page:
            params['page'] = page
        if page_size:
            params['page_size'] = page_size
        
        response = self._make_request("GET", "/media-assets/", params=params)
        return cast(Dict[str, Any], response)

    def get_frame_indices(self, media_asset_id=None, fetch_all=False, filters=None) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Get frame indices.
        
        Args:
            media_asset_id: The ID of the video/image set
            fetch_all: If True, automatically pages through ALL results (Critical for video sync)
            filters: Additional filters
        """
        params = {}
        if media_asset_id:
            params['media_asset'] = media_asset_id
        
        if filters:
            for key, value in filters.items():
                if value is not None and value != "":
                    params[key] = value
        
        if fetch_all:
            # Use the helper to get everything
            return self.get_all_pages("/frame-indices/", params=params)
            
        # Return standard paginated response
        return cast(Dict[str, Any], self._make_request("GET", "/frame-indices/", params=params))