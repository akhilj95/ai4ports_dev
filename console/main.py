import sys
import os
import signal
import subprocess
import threading
from datetime import datetime
import math

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QFrame, QStatusBar,
                             QTextEdit, QLineEdit, QMessageBox, QGroupBox, QSizePolicy, QSlider)
from PyQt6.QtCore import Qt, QProcess, QTimer, pyqtSignal, QPoint, QPointF, QRect
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QPolygonF, QBrush

# --- LOCAL IMPORTS ---
from src.video_thread_udp import VideoThreadUDP
from src.smart_video_thread import SmartVideoThread
from src.mavlink_worker import MavlinkWorker
from src.processing_worker import ProcessingWorker
import src.styles as styles


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

        # Telemetry State
        self.current_heading = 0.0
        self.current_depth = 0.0
        self.mavlink_worker = None

        # Mission State
        self.current_mission_name = None
        self.current_mission_folder = None
        self.current_session_path = None
        self.is_mission_active = False

        # --- SONAR CONFIG ---
        self.sonar_range_values = [3, 6, 9, 12, 15, 20, 25, 30]
        self.sonar_debounce_timer = QTimer()
        self.sonar_debounce_timer.setSingleShot(True)
        self.sonar_debounce_timer.setInterval(800)
        self.sonar_debounce_timer.timeout.connect(self.send_sonar_command_delayed)

        self.init_ui()
        self.start_background_threads()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # --- A. MISSION CONTROL HEADER ---
        mission_box = QGroupBox("Mission Control")
        mission_box.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        mission_box.setMaximumHeight(80)
        mission_box.setStyleSheet(styles.MISSION_BOX)

        mission_layout = QHBoxLayout(mission_box)
        mission_layout.setContentsMargins(10, 10, 10, 5)

        # 1. Create Mission
        self.widget_create_mission = QWidget()
        layout_create = QHBoxLayout(self.widget_create_mission)
        layout_create.setContentsMargins(0, 0, 0, 0)

        self.input_mission_name = QLineEdit()
        self.input_mission_name.setPlaceholderText("Enter Location / Mission Name")
        self.input_mission_name.setStyleSheet(styles.INPUT_FIELD)

        self.btn_create_mission = QPushButton("CREATE")
        self.btn_create_mission.setStyleSheet(styles.BTN_CREATE)
        self.btn_create_mission.clicked.connect(self.create_mission)

        layout_create.addWidget(QLabel("New Mission:"))
        layout_create.addWidget(self.input_mission_name)
        layout_create.addWidget(self.btn_create_mission)

        # 2. Active Mission
        self.widget_active_mission = QWidget()
        layout_active = QHBoxLayout(self.widget_active_mission)
        layout_active.setContentsMargins(0, 0, 0, 0)

        self.lbl_current_mission = QLabel()
        self.lbl_current_mission.setStyleSheet("font-size: 16px; font-weight: bold; color: #4CAF50; margin-left: 10px;")

        self.btn_finish_mission = QPushButton("FINISH")
        self.btn_finish_mission.setStyleSheet(styles.BTN_FINISH)
        self.btn_finish_mission.clicked.connect(self.finish_mission)

        layout_active.addWidget(QLabel("ACTIVE MISSION:"))
        layout_active.addWidget(self.lbl_current_mission)
        layout_active.addStretch()
        layout_active.addWidget(self.btn_finish_mission)

        self.widget_active_mission.setVisible(False)

        mission_layout.addWidget(self.widget_create_mission)
        mission_layout.addWidget(self.widget_active_mission)
        main_layout.addWidget(mission_box, 0)

        # --- B. SESSION UI WRAPPER ---
        self.widget_session_ui = QWidget()
        self.widget_session_ui.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout_session = QVBoxLayout(self.widget_session_ui)
        layout_session.setContentsMargins(0, 5, 0, 0)

        # --- VIDEO AREA (2-COLUMN LAYOUT) ---
        video_area = QWidget()
        video_layout = QHBoxLayout(video_area)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(5)

        # Labels
        self.lbl_main = self.create_video_label("Main Camera (Pilot)\n[Connecting...]")
        self.lbl_pana = self.create_video_label("Panasonic Recorder [UDP 5001]")
        self.lbl_sonar = self.create_video_label("Sonar View [UDP 5002]")
        self.lbl_proc = self.create_video_label("Processed Contour")
        self.lbl_proc.setVisible(False)

        # Left Column: Main Camera (60%)
        video_layout.addWidget(self.lbl_main, stretch=3)

        # Right Column: Vertical Layout
        right_column_widget = QWidget()
        right_layout = QVBoxLayout(right_column_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        # Right Top: Panasonic (Takes 2/3 vertical)
        right_layout.addWidget(self.lbl_pana, stretch=2)

        # Right Bottom: Container
        bottom_right_widget = QWidget()
        bottom_right_layout = QHBoxLayout(bottom_right_widget)
        bottom_right_layout.setContentsMargins(0, 0, 0, 0)
        bottom_right_layout.setSpacing(5)

        bottom_right_layout.addWidget(self.lbl_sonar)
        bottom_right_layout.addWidget(self.lbl_proc)

        right_layout.addWidget(bottom_right_widget, stretch=1)
        video_layout.addWidget(right_column_widget, stretch=2)

        layout_session.addWidget(video_area, 1)

        # --- CONTROLS AREA ---
        controls_frame = QFrame()
        controls_frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        controls_frame.setStyleSheet("background-color: #2d2d2d; border-radius: 8px; margin-top: 5px;")

        controls_layout = QHBoxLayout(controls_frame)
        controls_layout.setContentsMargins(10, 10, 10, 10)
        controls_layout.setSpacing(15)

        self.btn_start_session = QPushButton("● START RECORDING")
        self.btn_start_session.setStyleSheet(styles.BTN_START)
        self.btn_start_session.clicked.connect(self.start_session)

        self.btn_stop_session = QPushButton("■ STOP RECORDING")
        self.btn_stop_session.setEnabled(False)
        self.btn_stop_session.setStyleSheet(styles.BTN_STOP)
        self.btn_stop_session.clicked.connect(self.stop_session)

        self.btn_process = QPushButton("⚙️ PROCESS IMAGE")
        self.btn_process.setEnabled(False)
        self.btn_process.setStyleSheet(styles.BTN_PROCESS)
        self.btn_process.clicked.connect(self.run_processing)

        # --- SONAR SLIDER ---
        self.sonar_control_widget = QWidget()
        sonar_layout = QVBoxLayout(self.sonar_control_widget)
        sonar_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_sonar_range = QLabel("Sonar Range: 3m")
        self.lbl_sonar_range.setStyleSheet("color: white; font-weight: bold; font-size: 12px; margin-bottom: 2px;")
        self.lbl_sonar_range.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider_sonar_range = QSlider(Qt.Orientation.Horizontal)
        self.slider_sonar_range.setRange(0, len(self.sonar_range_values) - 1)
        self.slider_sonar_range.setValue(0)
        self.slider_sonar_range.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.slider_sonar_range.setTickInterval(1)
        self.slider_sonar_range.valueChanged.connect(self.on_sonar_slider_change)
        self.slider_sonar_range.setStyleSheet(styles.SLIDER_STYLE)

        sonar_layout.addWidget(self.lbl_sonar_range)
        sonar_layout.addWidget(self.slider_sonar_range)

        self.sonar_control_widget.setVisible(False)

        controls_layout.addWidget(self.btn_start_session, 1)
        controls_layout.addWidget(self.btn_stop_session, 1)
        controls_layout.addWidget(self.sonar_control_widget, 1)
        controls_layout.addWidget(self.btn_process, 1)

        layout_session.addWidget(controls_frame, 0)
        self.widget_session_ui.setVisible(False)
        main_layout.addWidget(self.widget_session_ui, 1)

        # --- LOG ---
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setStyleSheet(styles.LOG_OUTPUT)
        self.log_output.setVisible(False)
        main_layout.addWidget(self.log_output, 0)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        msg = "SYSTEM READY - DEBUG MODE ENABLED" if self.debug_mode else "SYSTEM READY"
        self.status_bar.showMessage(msg)

    def create_video_label(self, text):
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(styles.VIDEO_LABEL)
        lbl.setScaledContents(False)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        return lbl

    def start_background_threads(self):
        # 1. Start Mavlink Worker
        self.mavlink_worker = MavlinkWorker(ip="0.0.0.0", port=14552, debug_mode=self.debug_mode)
        self.mavlink_worker.connection_signal.connect(self.on_mavlink_connection)
        self.mavlink_worker.telemetry_signal.connect(self.update_telemetry)
        self.mavlink_worker.start()

        # 2. Start UDP Listeners
        self.thread_pana = VideoThreadUDP(5001, "Panasonic")
        self.thread_pana.change_pixmap_signal.connect(lambda x: self.set_pixmap_scaled(self.lbl_pana, x))
        self.thread_pana.start()

        self.thread_sonar = VideoThreadUDP(5002, "Sonar")
        self.thread_sonar.change_pixmap_signal.connect(lambda x: self.set_pixmap_scaled(self.lbl_sonar, x))
        self.thread_sonar.start()

    def update_telemetry(self, heading, depth):
        self.current_heading = heading
        self.current_depth = depth

    def on_mavlink_connection(self, connected, msg, boot_time):
        status_color = "#4CAF50" if connected else "#F44336"
        self.log_output.append(f"<span style='color:{status_color}'>[MAV] {msg}</span>")
        if connected and self.current_mission_folder:
            info_file = os.path.join(self.current_mission_folder, "mission_info.txt")
            try:
                with open(info_file, "a") as f:
                    f.write(f"MAV_CONNECTED: {datetime.now()}\n")
            except:
                pass

    # --- VIDEO & OVERLAY ---
    def set_pixmap_scaled(self, label, image):
        if image.isNull() or label.width() < 1 or label.height() < 1:
            return

        pix = QPixmap.fromImage(image)
        scaled = pix.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)

        if label == self.lbl_main:
            painter = QPainter(scaled)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            w = scaled.width()
            h = scaled.height()

            # --- 1. DEPTH (Bottom Left) ---
            depth_str = f"DEPTH: {self.current_depth:.1f} m"
            font_std = QFont("Consolas", 12, QFont.Weight.Bold)
            painter.setFont(font_std)
            metrics = painter.fontMetrics()

            box_h = metrics.height() + 10
            box_w = metrics.horizontalAdvance(depth_str) + 20
            margin = 15

            painter.setBrush(QColor(0, 0, 0, 150))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(margin, h - margin - box_h, box_w, box_h, 6, 6)

            painter.setPen(QColor(255, 255, 255))
            painter.drawText(margin + 10, h - margin - 8, depth_str)

            # --- 2. GRAPHICAL COMPASS (Bottom Right - RESIZED) ---
            comp_radius = 60  # Increased from 45
            comp_margin_x = 30
            comp_margin_y = 30
            center_x = w - comp_margin_x - comp_radius
            center_y = h - comp_margin_y - comp_radius

            # 2a. Background
            painter.setBrush(QColor(0, 0, 0, 120))
            painter.setPen(QPen(QColor(200, 200, 200, 100), 2))
            painter.drawEllipse(QPoint(center_x, center_y), comp_radius, comp_radius)

            # 2b. Fixed Letters (N/E/S/W)
            font_card = QFont("Arial", 12, QFont.Weight.Bold)  # Increased font from 10 to 12
            painter.setFont(font_card)

            # N (Red)
            painter.setPen(QColor(255, 60, 60))
            painter.drawText(QRect(center_x - 15, center_y - comp_radius - 10, 30, 20), Qt.AlignmentFlag.AlignCenter,
                             "N")

            # E, S, W (White)
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(QRect(center_x + comp_radius - 5, center_y - 10, 30, 20), Qt.AlignmentFlag.AlignCenter,
                             "E")
            painter.drawText(QRect(center_x - 15, center_y + comp_radius - 5, 30, 20), Qt.AlignmentFlag.AlignCenter,
                             "S")
            painter.drawText(QRect(center_x - comp_radius - 25, center_y - 10, 30, 20), Qt.AlignmentFlag.AlignCenter,
                             "W")

            # 2c. Rotating Triangle
            painter.save()
            painter.translate(center_x, center_y)
            painter.rotate(self.current_heading)

            painter.setBrush(QColor(255, 215, 0))  # Gold
            painter.setPen(Qt.PenStyle.NoPen)
            # Scaled up triangle slightly to match new radius
            triangle = QPolygonF([
                QPointF(0, -comp_radius + 5),
                QPointF(-8, -comp_radius + 25),
                QPointF(8, -comp_radius + 25)
            ])
            painter.drawPolygon(triangle)

            painter.restore()

            # 2d. Readout
            font_val = QFont("Consolas", 11, QFont.Weight.Bold)  # Increased from 10
            painter.setFont(font_val)
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(QRect(center_x - 30, center_y - 12, 60, 24),
                             Qt.AlignmentFlag.AlignCenter, f"{int(self.current_heading)}°")

            painter.end()

        label.setPixmap(scaled)

    # --- SLIDER LOGIC ---
    def on_sonar_slider_change(self):
        idx = self.slider_sonar_range.value()
        val = self.sonar_range_values[idx]
        self.lbl_sonar_range.setText(f"Sonar Range: {val}m")
        self.sonar_debounce_timer.start()

    def send_sonar_command_delayed(self):
        idx = self.slider_sonar_range.value()
        val = float(self.sonar_range_values[idx])
        if self.proc_sonar and self.proc_sonar.poll() is None:
            try:
                cmd = f"RANGE {val:.1f}\n"
                self.proc_sonar.stdin.write(cmd.encode('utf-8'))
                self.proc_sonar.stdin.flush()
                self.log_output.append(f"[CMD] Sent Sonar Range: {val:.1f}m")
            except Exception as e:
                self.log_output.append(f"[ERR] Failed to send range: {e}")

    # --- MISSION & SESSION LOGIC ---
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

        self.current_mission_name = name
        self.is_mission_active = True
        self.log_output.append(f">>> MISSION CREATED: {name}")
        self.status_bar.showMessage(f"Mission Active: {name}")

        self.widget_create_mission.setVisible(False)
        self.lbl_current_mission.setText(name)
        self.widget_active_mission.setVisible(True)

        self.widget_session_ui.setVisible(True)
        self.sonar_control_widget.setVisible(True)
        self.slider_sonar_range.setValue(0)

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
        self.sonar_control_widget.setVisible(False)

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
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0

        try:
            p = subprocess.Popen([exe] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE,
                                 creationflags=creationflags, text=False)
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
                if decoded: print(f"{prefix} {decoded}")
            except:
                pass

    def stop_session(self):
        self.log_output.append(">>> SESSION STOPPING...")
        if self.thread_main: self.thread_main.stop_recording()
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
        self.lbl_proc.setVisible(False)
        self.lbl_proc.clear()
        self.lbl_proc.setText("Processed Contour")

    def show_processed_view(self):
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
            try:
                if proc.stdin: proc.stdin.close()
                if os.name == 'nt':
                    proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    proc.send_signal(signal.SIGINT)
                proc.wait(timeout=5)
            except:
                proc.kill()

    def run_processing(self):
        if not self.current_session_path or not os.path.exists(self.current_session_path):
            QMessageBox.warning(self, "Error", "No active or recent session found to process.")
            return

        img_folder = os.path.join(self.current_session_path, "camera_1", "images")

        # NOTE: WE DO NOT SEARCH FILES HERE ANYMORE to prevent freezing.
        # We just pass the folder to the thread.

        ext = ".exe" if os.name == 'nt' else ""
        contour_bin = f"./bin/contour{ext}"

        self.show_processed_view()
        self.lbl_proc.setText("Processing...\n(Please Wait)")
        self.btn_process.setEnabled(False)

        # Pass folder, not file
        self.processing_worker = ProcessingWorker(contour_bin, img_folder)
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
            data = proc.readAllStandardError() if is_err else proc.readAllStandardOutput()
            prefix = "[ERR]" if is_err else "[DRV]"
            text = bytes(data).decode("utf8", errors="ignore").strip()
            if text: self.log_output.append(f"{prefix} {text}")
        except:
            pass

    def closeEvent(self, event):
        if self.thread_main: self.thread_main.stop()
        if self.mavlink_worker: self.mavlink_worker.stop()
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