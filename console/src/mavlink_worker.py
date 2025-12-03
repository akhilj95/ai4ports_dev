from PyQt6.QtCore import QThread, pyqtSignal

try:
    from pymavlink import mavutil
except ImportError:
    mavutil = None

class MavlinkWorker(QThread):
    # Signal: (success, status_message, boot_time_ms)
    finished_signal = pyqtSignal(bool, str, int)

    def __init__(self, ip="0.0.0.0", port=14552):
        super().__init__()
        self.ip = ip
        self.port = port

    def run(self):
        if not mavutil:
            self.finished_signal.emit(False, "Pymavlink library missing", 0)
            return

        conn_str = f'udpin:{self.ip}:{self.port}'
        
        try:
            # source_system=255 identifies us as a GCS
            master = mavutil.mavlink_connection(conn_str, source_system=255)
            
            # 1. Wait for Heartbeat
            master.wait_heartbeat(timeout=3)
            
            # 2. Wait for SYSTEM_TIME (contains time_boot_ms)
            msg = master.recv_match(type='SYSTEM_TIME', blocking=True, timeout=2)
            
            if msg:
                self.finished_signal.emit(True, "Data Acquired", msg.time_boot_ms)
            else:
                self.finished_signal.emit(False, "Connected, but no time data", 0)
                
        except Exception as e:
            self.finished_signal.emit(False, f"Mavlink Error: {str(e)}", 0)