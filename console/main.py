import sys
import os
import signal
import glob
import subprocess
import threading
from datetime import datetime
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QFrame, QStatusBar,
                             QTextEdit, QLineEdit, QMessageBox, QGroupBox, QSizePolicy)
from PyQt6.QtCore import Qt, QProcess, QTimer, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from src.video_thread_udp import VideoThreadUDP
from src.smart_video_thread import SmartVideoThread
from src.mavlink_worker import MavlinkWorker


# --- WORKER THREAD FOR PROCESSING ---
class ProcessingWorker(QThread):
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, executable, input_path, output_path):
        super().__init__()
        self.executable = executable
        self.input_path = input_path
        self.output_path = output_path

    def run(self):
        if not os.path.exists(self.executable):
            self.finished_signal.emit(False, f"Executable not found: {self.executable}", "")
            return

        try:
            result = subprocess.run(
                [self.executable, self.input_path, self.output_path],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                self.finished_signal.emit(True, "Processing Complete", self.output_path)
            else:
                self.finished_signal.emit(False, f"Process Failed: {result.stderr}", "")
        except Exception as e:
            self.finished_signal.emit(False, f"Execution Error: {str(e)}", "")


class ROVConsole(QMainWindow):
    def __init__(self, debug_mode=False):
        super().__init__()
        self.setWindowTitle("BlueROV Command Center")
        self.setGeometry(100, 100, 1280, 800)

        self.debug_mode = debug_mode
        if self.debug_mode:
            self.setWindowTitle("BlueROV Command Center [DEBUG MODE - WEBCAM]")

        self.proc_panasonic = None
        self.proc_sonar = None

        self.thread_main = None
        self.thread_pana = None
        self.thread_sonar = None
        self.processing_worker = None
        self.mavlink_worker = None

        # Mission State
        self.current_mission_name = None
        self.current_mission_folder = None
        self.current_session_path = None
        self.is_mission_active = False

        self.init_ui()
        self.start_preview_listeners()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        # Reduce spacing between main sections to maximize screen real estate
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # --- A. MISSION CONTROL HEADER (COMPACT) ---
        mission_box = QGroupBox("Mission Control")
        # Fixed Height Policy ensures it doesn't grow
        mission_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        mission_box.setMaximumHeight(80)  # Force it small

        mission_box.setStyleSheet("""
            QGroupBox { 
                font-weight: bold; border: 1px solid #444; background-color: #222; 
                margin-top: 6px; padding-top: 5px; 
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
        """)
        mission_layout = QHBoxLayout(mission_box)
        mission_layout.setContentsMargins(10, 10, 10, 5)  # Tight margins

        # 1. State: Create Mission
        self.widget_create_mission = QWidget()
        layout_create = QHBoxLayout(self.widget_create_mission)
        layout_create.setContentsMargins(0, 0, 0, 0)

        self.input_mission_name = QLineEdit()
        self.input_mission_name.setPlaceholderText("Enter Location / Mission Name")
        self.input_mission_name.setStyleSheet(
            "padding: 5px; color: white; background-color: #333; border: 1px solid #555; font-size: 13px;")

        self.btn_create_mission = QPushButton("CREATE")
        self.btn_create_mission.setStyleSheet("""
            QPushButton {
                background-color: #2196F3; color: white; font-weight: bold; padding: 5px 15px; 
                font-size: 13px; border-radius: 4px; border: 1px solid #1976D2;
            }
            QPushButton:hover { background-color: #42A5F5; }
        """)
        self.btn_create_mission.clicked.connect(self.create_mission)

        layout_create.addWidget(QLabel("New Mission:"))
        layout_create.addWidget(self.input_mission_name)
        layout_create.addWidget(self.btn_create_mission)

        # 2. State: Active Mission
        self.widget_active_mission = QWidget()
        layout_active = QHBoxLayout(self.widget_active_mission)
        layout_active.setContentsMargins(0, 0, 0, 0)

        self.lbl_current_mission = QLabel()
        self.lbl_current_mission.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50; margin-left: 10px;")

        self.btn_finish_mission = QPushButton("FINISH")
        self.btn_finish_mission.setStyleSheet("""
            QPushButton {
                background-color: #C62828; color: white; font-weight: bold; padding: 5px 15px; 
                font-size: 13px; border-radius: 4px; border: 1px solid #B71C1C;
            }
            QPushButton:hover { background-color: #E53935; }
        """)
        self.btn_finish_mission.clicked.connect(self.finish_mission)

        layout_active.addWidget(QLabel("ACTIVE MISSION:"))
        layout_active.addWidget(self.lbl_current_mission)
        layout_active.addStretch()
        layout_active.addWidget(self.btn_finish_mission)

        self.widget_active_mission.setVisible(False)

        mission_layout.addWidget(self.widget_create_mission)
        mission_layout.addWidget(self.widget_active_mission)

        # ADD TO MAIN LAYOUT -> Stretch = 0 (Do not expand)
        main_layout.addWidget(mission_box, 0)

        # --- B. SESSION UI WRAPPER (EXPANDING) ---
        self.widget_session_ui = QWidget()
        # Expanding Policy ensures it takes all remaining space
        self.widget_session_ui.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout_session = QVBoxLayout(self.widget_session_ui)
        layout_session.setContentsMargins(0, 5, 0, 0)

        # --- VIDEO LAYOUT ---
        video_area = QWidget()
        video_layout = QHBoxLayout(video_area)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(5)

        # 1. Left Side: Main Camera (Large)
        self.lbl_main = self.create_video_label("Main Camera (Pilot)\n[Connecting...]")
        # Stretch 4: Gives Main Camera 80% of width relative to sidebar
        video_layout.addWidget(self.lbl_main, stretch=4)

        # 2. Right Side: Vertical Column
        right_sidebar = QWidget()
        right_layout = QVBoxLayout(right_sidebar)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        self.lbl_pana = self.create_video_label("Panasonic Recorder [UDP 5001]")
        self.lbl_sonar = self.create_video_label("Sonar View [UDP 5002]")
        self.lbl_proc = self.create_video_label("Processed Contour")
        self.lbl_proc.setVisible(False)

        # Equal weighting in the sidebar column
        right_layout.addWidget(self.lbl_pana, 1)
        right_layout.addWidget(self.lbl_sonar, 1)
        right_layout.addWidget(self.lbl_proc, 1)

        # Add right sidebar to main video layout (Stretch 1)
        video_layout.addWidget(right_sidebar, stretch=1)

        # Add Video Area to Session Layout (Stretch 1 -> Take all vertical space)
        layout_session.addWidget(video_area, 1)

        # --- CONTROLS (COMPACT) ---
        controls_frame = QFrame()
        controls_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        controls_frame.setStyleSheet("background-color: #2d2d2d; border-radius: 8px; margin-top: 5px;")

        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(10, 10, 10, 10)  # Reduced margins
        controls_layout.setSpacing(15)

        style_common = "font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px;"

        self.btn_start_session = QPushButton("● START RECORDING")
        self.btn_start_session.setStyleSheet(
            f"QPushButton {{ background-color: #2E7D32; color: white; border: 1px solid #1B5E20; {style_common} }} QPushButton:hover {{ background-color: #388E3C; }}")
        self.btn_start_session.clicked.connect(self.start_session)

        self.btn_stop_session = QPushButton("■ STOP RECORDING")
        self.btn_stop_session.setEnabled(False)
        self.btn_stop_session.setStyleSheet(
            f"QPushButton {{ background-color: #C62828; color: white; border: 1px solid #B71C1C; {style_common} }} QPushButton:hover {{ background-color: #D32F2F; }} QPushButton:disabled {{ background-color: #444; color: #888; border: 1px solid #333; }}")
        self.btn_stop_session.clicked.connect(self.stop_session)

        self.btn_process = QPushButton("⚙️ PROCESS IMAGE")
        self.btn_process.setEnabled(False)
        self.btn_process.setStyleSheet(
            f"QPushButton {{ background-color: #1565C0; color: white; border: 1px solid #0D47A1; {style_common} }} QPushButton:hover {{ background-color: #1976D2; }} QPushButton:disabled {{ background-color: #444; color: #888; border: 1px solid #333; }}")
        self.btn_process.clicked.connect(self.run_processing)

        controls_layout.addWidget(self.btn_start_session)
        controls_layout.addWidget(self.btn_stop_session)
        controls_layout.addWidget(self.btn_process)

        # Add Controls to Session Layout (Stretch 0)
        layout_session.addWidget(controls_frame, 0)

        self.widget_session_ui.setVisible(False)

        # ADD SESSION UI TO MAIN LAYOUT -> Stretch = 1 (Take all remaining vertical space)
        main_layout.addWidget(self.widget_session_ui, 1)

        # --- C. LOG (COMPACT) ---
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setPlaceholderText("System Logs...")
        self.log_output.setMaximumHeight(80)  # Small log window
        self.log_output.setStyleSheet(
            "background-color: #000; color: #0f0; font-family: Consolas; border: 1px solid #444; font-size: 11px;")
        self.log_output.setVisible(False)
        main_layout.addWidget(self.log_output, 0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        if self.debug_mode:
            self.status_bar.showMessage("SYSTEM READY - DEBUG MODE ENABLED")
        else:
            self.status_bar.showMessage("SYSTEM READY")

    def create_video_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("background-color: #111; color: #555; border: 1px solid #333;")
        lbl.setScaledContents(False)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        return lbl

    def set_pixmap_scaled(self, label, image):
        if not image.isNull():
            if label.width() < 1 or label.height() < 1:
                return
            pix = QPixmap.fromImage(image)
            scaled = pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(scaled)

    def start_preview_listeners(self):
        self.thread_pana = VideoThreadUDP(5001, "Panasonic")
        self.thread_pana.change_pixmap_signal.connect(lambda x: self.set_pixmap_scaled(self.lbl_pana, x))
        self.thread_pana.start()

        self.thread_sonar = VideoThreadUDP(5002, "Sonar")
        self.thread_sonar.change_pixmap_signal.connect(lambda x: self.set_pixmap_scaled(self.lbl_sonar, x))
        self.thread_sonar.start()

    def save_mavlink_data(self, success, msg, boot_time_ms):
        if not self.current_mission_folder:
            return

        info_file = os.path.join(self.current_mission_folder, "mission_info.txt")

        if success:
            millis = boot_time_ms % 1000
            total_seconds = boot_time_ms // 1000
            seconds = total_seconds % 60
            minutes = (total_seconds // 60) % 60
            hours = total_seconds // 3600

            uptime_str = "{:d}:{:02d}:{:02d}.{:03d}".format(hours, minutes, seconds, millis)

            self.log_output.append(f">>> ROV ONLINE. Uptime: {uptime_str}")

            try:
                with open(info_file, "a") as f:
                    f.write(f"ROV_BOOT_TIME_MS: {boot_time_ms}\n")
                    f.write(f"ROV_UPTIME: {uptime_str}\n")
                    f.write(f"DATA_ACQUIRED: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}\n")
            except Exception as e:
                self.log_output.append(f"[ERR] File write failed: {e}")

        else:
            self.log_output.append(f"[MAV ERR] Connection Failed: {msg}")
            print(f"[MAV ERR] {msg}")
            
            try:
                with open(info_file, "a") as f:
                    f.write(f"ROV_CONNECTION_FAILED: {msg}\n")
            except Exception:
                pass

    def create_mission(self):
        name = self.input_mission_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Please enter a mission name.")
            return

        date_str = datetime.now().strftime("%Y_%m_%d")
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')

        self.current_mission_folder = os.path.join("data", date_str, safe_name)
        if not os.path.exists(self.current_mission_folder):
            os.makedirs(self.current_mission_folder)

        info_file = os.path.join(self.current_mission_folder, "mission_info.txt")
        with open(info_file, "a") as f:
            f.write(f"Mission: {name}\n")
            f.write(f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-" * 20 + "\n")

        if hasattr(self, 'mavlink_worker') and self.mavlink_worker and self.mavlink_worker.isRunning():
            self.mavlink_worker.terminate()
            self.mavlink_worker.wait()

        self.mavlink_worker = MavlinkWorker(ip="0.0.0.0", port=14552)
        self.mavlink_worker.finished_signal.connect(self.save_mavlink_data)
        self.mavlink_worker.start()

        self.current_mission_name = name
        self.is_mission_active = True
        self.log_output.append(f">>> MISSION CREATED: {name}")
        self.status_bar.showMessage(f"Mission Active: {name}")

        self.widget_create_mission.setVisible(False)
        self.lbl_current_mission.setText(name)
        self.widget_active_mission.setVisible(True)

        self.widget_session_ui.setVisible(True)
        self.log_output.setVisible(True)

        if not self.thread_main:
            self.thread_main = SmartVideoThread(debug_mode=self.debug_mode)
            self.thread_main.change_pixmap_signal.connect(lambda x: self.set_pixmap_scaled(self.lbl_main, x))
            self.thread_main.log_signal.connect(self.log_output.append)
            self.thread_main.start()

        self.btn_start_session.setEnabled(True)
        self.reset_processed_view()

    def finish_mission(self):
        self.is_mission_active = False
        self.log_output.append(f">>> MISSION FINISHED: {self.current_mission_name}")

        self.widget_active_mission.setVisible(False)
        self.widget_session_ui.setVisible(False)
        self.log_output.setVisible(False)

        if self.thread_main:
            self.thread_main.stop()
            self.thread_main.wait()
            self.thread_main = None

        self.input_mission_name.clear()
        self.widget_create_mission.setVisible(True)

        self.btn_start_session.setEnabled(False)
        self.btn_process.setEnabled(False)

        self.current_session_path = None
        self.lbl_proc.setVisible(False)
        self.status_bar.showMessage("Mission Finished. Ready for new mission.")

    def start_session(self):
        if not self.is_mission_active:
            return

        self.log_output.append(">>> SESSION STARTING...")

        session_id = f"session_{datetime.now().strftime('%H_%M_%S')}"
        session_full_path = os.path.join(self.current_mission_folder, session_id)
        self.current_session_path = os.path.abspath(session_full_path)

        if not os.path.exists(self.current_session_path):
            os.makedirs(self.current_session_path)

        camera0_path = os.path.join(self.current_session_path, "camera_0")
        if not os.path.exists(camera0_path):
            os.makedirs(camera0_path)

        self.log_output.append(f"[INFO] Saving session to: {self.current_session_path}")

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        main_cam_file = os.path.join(camera0_path, f"main_rec_{timestamp_str}.mkv")

        if self.thread_main:
            self.thread_main.start_recording(main_cam_file)

        ext = ".exe" if os.name == 'nt' else ""
        drv_args = ["--out", self.current_session_path]
        if self.debug_mode:
            drv_args.append("--debug")

        self.proc_panasonic = self.create_process(f"./bin/panasonic_driver{ext}", drv_args)
        if not self.proc_panasonic:
            self.log_output.append("[WARN] Panasonic Driver failed to start.")

        self.proc_sonar = self.create_process(f"./bin/sonoptix_driver{ext}", drv_args)
        if not self.proc_sonar:
            self.log_output.append("[WARN] Sonar Driver failed to start.")

        self.btn_start_session.setEnabled(False)
        self.btn_stop_session.setEnabled(True)
        self.btn_finish_mission.setVisible(False)

        self.btn_process.setEnabled(True)
        self.reset_processed_view()

    def create_process(self, exe, args):
        proc = QProcess()
        proc.readyReadStandardOutput.connect(lambda: self.handle_log(proc))
        proc.readyReadStandardError.connect(lambda: self.handle_log(proc, is_err=True))

        if os.name == 'nt':
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            creationflags = 0

        try:
            p = subprocess.Popen(
                [exe] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=creationflags,
                text=False
            )

            t_out = threading.Thread(target=self.read_popen_output, args=(p, False))
            t_err = threading.Thread(target=self.read_popen_output, args=(p, True))
            t_out.daemon = True
            t_err.daemon = True
            t_out.start()
            t_err.start()

            return p
        except Exception as e:
            self.log_output.append(f"[ERR] Failed to start {exe}: {e}")
            return None

    def read_popen_output(self, proc, is_err):
        stream = proc.stderr if is_err else proc.stdout
        prefix = "[DRV_ERR]" if is_err else "[DRV]"
        while True:
            line = stream.readline()
            if not line: break
            try:
                decoded = line.decode('utf-8', errors='ignore').strip()
                if decoded:
                    print(f"{prefix} {decoded}")
            except:
                pass

    def stop_session(self):
        self.log_output.append(">>> SESSION STOPPING...")

        if self.thread_main:
            self.thread_main.stop_recording()

        self.kill_process(self.proc_panasonic)
        self.kill_process(self.proc_sonar)

        self.proc_panasonic = None
        self.proc_sonar = None

        self.btn_start_session.setEnabled(True)
        self.btn_stop_session.setEnabled(False)
        self.btn_finish_mission.setVisible(True)

        self.btn_process.setEnabled(False)
        QTimer.singleShot(500, self.clear_driver_feeds)

    def reset_processed_view(self):
        """Hides the processed view to make space for the other feeds"""
        self.lbl_proc.setVisible(False)
        self.lbl_proc.clear()
        self.lbl_proc.setText("Processed Contour")

    def show_processed_view(self):
        """Shows the processed view in the sidebar"""
        self.lbl_proc.setVisible(True)

    def clear_driver_feeds(self):
        self.lbl_pana.clear()
        self.lbl_pana.setText("Panasonic Recorder [UDP 5001]\n[Offline]")
        self.lbl_sonar.clear()
        self.lbl_sonar.setText("Sonar View [UDP 5002]\n[Offline]")
        self.reset_processed_view()

    def kill_process(self, proc):
        if not proc: return

        if proc.poll() is None:
            self.log_output.append(f"Stopping process {proc.pid}...")
            
            try:
                if os.name == 'nt':
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)

                try:
                    proc.wait(timeout=5) 
                except subprocess.TimeoutExpired:
                    self.log_output.append("[WARN] Cleanup timed out. Force killing...")
                    proc.kill()
                    proc.wait()
                    
            except Exception as e:
                self.log_output.append(f"[ERR] Stop failed: {e}")
                try:
                    proc.kill()
                except:
                    pass

    def run_processing(self):
        if not self.current_session_path or not os.path.exists(self.current_session_path):
            QMessageBox.warning(self, "Error", "No active or recent session found to process.")
            return

        img_folder = os.path.join(self.current_session_path, "camera_1", "images")
        if not os.path.exists(img_folder):
            self.log_output.append(f"[ERR] No images folder found: {img_folder}")
            return

        list_of_files = glob.glob(os.path.join(img_folder, "*.jpg"))
        if not list_of_files:
            self.log_output.append("[ERR] No images found to process.")
            return

        latest_file = max(list_of_files, key=os.path.getctime)
        self.log_output.append(f"[INFO] Processing latest image: {os.path.basename(latest_file)}")

        output_filename = f"processed_{os.path.basename(latest_file)}"
        output_path = os.path.join(self.current_session_path, "camera_1", "images", output_filename)

        ext = ".exe" if os.name == 'nt' else ""
        contour_bin = f"./bin/contour{ext}"

        self.show_processed_view()
        self.lbl_proc.setText("Processing...\n(Please Wait)")

        self.btn_process.setEnabled(False)

        self.processing_worker = ProcessingWorker(contour_bin, latest_file, output_path)
        self.processing_worker.finished_signal.connect(self.on_processing_finished)
        self.processing_worker.start()

    def on_processing_finished(self, success, msg, output_path):
        if self.btn_stop_session.isEnabled():
            self.btn_process.setEnabled(True)
        else:
            self.btn_process.setEnabled(False)

        if success:
            self.log_output.append(f">>> {msg}")
            pix = QPixmap(output_path)
            if not pix.isNull():
                self.set_pixmap_scaled(self.lbl_proc, pix.toImage())
            else:
                self.lbl_proc.setText("Error loading processed image")
        else:
            self.log_output.append(f"[ERR] {msg}")
            self.lbl_proc.setText("Processing Failed")

    def handle_log(self, proc, is_err=False):
        try:
            if is_err:
                data = proc.readAllStandardError()
                prefix = "[ERR]"
            else:
                data = proc.readAllStandardOutput()
                prefix = "[DRV]"

            text = bytes(data).decode("utf8", errors="ignore").strip()
            if text:
                self.log_output.append(f"{prefix} {text}")
                self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())
        except RuntimeError:
            pass

    def closeEvent(self, event):
        if self.thread_main:
            self.thread_main.stop()
        self.kill_process(self.proc_panasonic)
        self.kill_process(self.proc_sonar)
        event.accept()


if __name__ == "__main__":
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(sys.executable))
    else:
        os.chdir(os.path.dirname(os.path.abspath(__file__)))

    app = QApplication(sys.argv)
    app.setStyleSheet("QMainWindow { background-color: #1e1e1e; } QLabel { color: #ccc; }")

    debug = "--debug" in sys.argv

    window = ROVConsole(debug_mode=debug)
    window.show()
    sys.exit(app.exec())