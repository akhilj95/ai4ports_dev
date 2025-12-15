import time
import math
from PyQt6.QtCore import QThread, pyqtSignal

try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None


class MavlinkWorker(QThread):
    # Signal: (is_connected, status_message, boot_time_ms)
    connection_signal = pyqtSignal(bool, str, int)
    # Signal: (heading, depth) - Emitted continuously
    telemetry_signal = pyqtSignal(float, float)

    def __init__(self, ip="0.0.0.0", port=14552, debug_mode=False):
        super().__init__()
        self.ip = ip
        self.port = port
        self.debug_mode = debug_mode
        self.running = True

        # NEW: Store the latest sync data thread-safely
        self.latest_boot_time_ms = 0
        self.latest_unix_time = 0

    def run(self):
        # --- DEBUG MODE SIMULATION ---
        if self.debug_mode:
            self.connection_signal.emit(True, "DEBUG MODE: Simulating Data", 0)
            sim_heading = 0.0
            sim_depth = 0.0
            step = 0
            while self.running:
                # Simulate typical ROV movement
                sim_heading = (sim_heading + 1) % 360
                sim_depth = abs(5 * math.sin(step * 0.05))  # Oscillate between 0m and 5m

                self.telemetry_signal.emit(sim_heading, sim_depth)
                step += 1
                time.sleep(0.1)  # 10Hz update rate
            return

        # --- REAL MAVLINK CONNECTION ---
        if not mavutil:
            self.connection_signal.emit(False, "Pymavlink library missing", 0)
            return

        conn_str = f'udpin:{self.ip}:{self.port}'
        master = None

        try:
            # source_system=255 identifies us as a GCS
            master = mavutil.mavlink_connection(conn_str, source_system=255)

            # Wait for Heartbeat (Connection Check)
            master.wait_heartbeat(timeout=3)

            # Request Data Stream (Ensure ROV sends VFR_HUD)
            # MAV_DATA_STREAM_ALL = 0, Rate = 4Hz
            master.mav.request_data_stream_send(
                master.target_system, master.target_component,
                mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1
            )

            # Get Boot Time for logging
            msg_time = master.recv_match(type='SYSTEM_TIME', blocking=True, timeout=2)
            boot_time = msg_time.time_boot_ms if msg_time else 0
            self.connection_signal.emit(True, "Mavlink Connected", boot_time)

        except Exception as e:
            self.connection_signal.emit(False, f"Connection Error: {str(e)}", 0)
            return

        # --- TELEMETRY LOOP ---
        while self.running:
            try:
                # Filter for VFR_HUD messages which contain Heading and Alt (Depth)
                msg = master.recv_match(type=['VFR_HUD', 'SYSTEM_TIME'], blocking=True, timeout=1.0)

                if msg:
                    msg_type = msg.get_type()

                    if msg_type == 'VFR_HUD':
                        heading = float(msg.heading)
                        depth = float(msg.alt) # or -msg.alt depending on setup
                        self.telemetry_signal.emit(heading, depth)

                    elif msg_type == 'SYSTEM_TIME':
                        # Capture the pair: (PC Time, ROV Boot Time)
                        self.latest_unix_time = time.time() # PC Time
                        self.latest_boot_time_ms = msg.time_boot_ms # ROV Time

            except Exception:
                # Allow timeout to check self.running flag
                pass

        if master:
            master.close()

    def stop(self):
        self.running = False
        self.wait()