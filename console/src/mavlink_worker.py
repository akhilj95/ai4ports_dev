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
                msg = master.recv_match(type='VFR_HUD', blocking=True, timeout=1.0)

                if msg:
                    # msg.heading is in degrees (0..360)
                    # msg.alt is altitude in meters (positive). ROV depth is often negative alt or handled differently.
                    # We will assume 'alt' is what we want, or -alt if needed.
                    # Usually VFR_HUD.alt on ArduSub is Depth.
                    heading = float(msg.heading)
                    depth = float(msg.alt)
                    self.telemetry_signal.emit(heading, depth)

            except Exception:
                # Allow timeout to check self.running flag
                pass

        if master:
            master.close()

    def stop(self):
        self.running = False
        self.wait()