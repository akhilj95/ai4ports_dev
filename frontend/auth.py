# auth.py
import streamlit as st
import requests
from streamlit_cookies_manager import EncryptedCookieManager
import traceback

# --- Configuration ---
COOKIE_SECRET = "a-very-strong-and-secret-key-for-testing"
API_BASE_URL = "http://127.0.0.1:8000/api"
TOKEN_URL = f"{API_BASE_URL}/token/"
REFRESH_URL = f"{API_BASE_URL}/token/refresh/"
USER_INFO_URL = f"{API_BASE_URL}/me/"


# --- Helper to get the session-specific cookie manager ---
def get_cookies():
    """
    Instantiates the component. This MUST run on every script execution
    so the component can render and stay in sync.
    """
    return EncryptedCookieManager(
        prefix="my_app_cookie_",
        password=COOKIE_SECRET
    )


# --- Logout Function ---
def logout():
    """Clears all session state and browser cookies."""
    # This is called on a new script run (from on_click),
    # so calling get_cookies() here is fine.
    cookies = get_cookies()
    for key in list(st.session_state.keys()):
        del st.session_state[key]

    if 'token' in cookies:
        del cookies['token']
    if 'refresh' in cookies:
        del cookies['refresh']
    cookies.save()
    st.rerun()


# --- Login Form UI ---
# THIS FUNCTION NOW ACCEPTS 'cookies' AS AN ARGUMENT
def login_form(cookies):
    """Displays the login form and handles submission."""
    # cookies = get_cookies() # <-- REMOVED

    st.title("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        try:
            response = requests.post(TOKEN_URL, data={"username": username, "password": password})
            response.raise_for_status()

            response_data = response.json()

            st.session_state['token'] = response_data['access']
            st.session_state['refresh'] = response_data['refresh']
            st.session_state['role'] = response_data.get('role', 'user')
            st.session_state['username'] = response_data.get('username', 'Guest')

            cookies['token'] = response_data['access']
            cookies['refresh'] = response_data['refresh']
            cookies.save()
            st.rerun()

        except requests.exceptions.HTTPError as err:
            if err.response.status_code in [400, 401]:
                st.error("Invalid username or password")
            else:
                st.error(f"HTTP Error: {err}")
        except requests.exceptions.ConnectionError:
            st.error("Failed to connect to the server. Is it running?")
        except Exception as e:
            st.error(f"An error occurred: {e!r}")
            st.error(traceback.format_exc())


# --- Logic for Refreshing Token (on page load) ---
# THIS FUNCTION NOW ACCEPTS 'cookies' AS AN ARGUMENT
def try_refresh_login(cookies):
    """
    Tries to log in using a refresh token from cookies.
    Returns True on success, False on failure.
    """
    # cookies = get_cookies() # <-- REMOVED

    # We can't do anything if the component isn't ready.
    if not cookies.ready():
        return False

    if 'refresh' not in cookies:
        return False

    try:
        refresh_token = cookies['refresh']
        refresh_response = requests.post(REFRESH_URL, data={'refresh': refresh_token})
        refresh_response.raise_for_status()

        response_data = refresh_response.json()
        access_token = response_data['access']
        refresh_token = response_data.get('refresh', refresh_token)

        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(USER_INFO_URL, headers=headers)
        user_response.raise_for_status()

        user_data = user_response.json()
        st.session_state['token'] = access_token
        st.session_state['refresh'] = refresh_token
        st.session_state['role'] = user_data.get('role', 'user')
        st.session_state['username'] = user_data.get('username', 'Guest')

        cookies['token'] = access_token
        cookies['refresh'] = refresh_token
        cookies.save()
        return True

    except Exception as e:
        # Don't show an error, just fail silently and show login form
        print(f"Failed to refresh session: {e!r}")

        # Clear bad cookies
        if 'token' in cookies: del cookies['token']
        if 'refresh' in cookies: del cookies['refresh']
        return False


# --- Main Auth Guard Function ---
def check_auth():
    """
    The main authentication guard.
    Call this at the top of every page.
    """

    # This instantiates the component ONCE per script run
    cookies = get_cookies()

    # 1. Check if we're already logged in (in session state)
    if 'token' in st.session_state:
        with st.sidebar:
            st.title(f"Welcome, {st.session_state.get('username', 'User')}!")
            st.write(f"**Role:** `{st.session_state.get('role', 'user')}`")
            st.button("Logout", on_click=logout)
        return  # We're logged in, continue.

    # 2. Check if the component is ready
    if not cookies.ready():
        # Component isn't ready. Show a message and stop.
        # This will rerun until it's ready.
        st.info("Initializing session, please wait...")
        st.stop()

    # 3. Component is ready. Try to log in from a cookie.
    #    PASS the 'cookies' object to the function.
    if try_refresh_login(cookies):
        # Login was successful! Rerun to show the main app.
        st.rerun()

    # 4. Component is ready, but refresh failed (no cookie or expired).
    #    Show the login form. PASS the 'cookies' object.
    login_form(cookies)
    st.stop()