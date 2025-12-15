import sys
import os
import cv2
import numpy as np
import subprocess
import threading
import time
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class SmartVideoThread(QThread):
    change_pixmap_signal = pyqtSignal(QImage)
    log_signal = pyqtSignal(str)

    def __init__(self, debug_mode=False):
        super().__init__()
        self.run_flag = True
        self.restart_requested = False  # Flag to trigger FFmpeg restart
        self.process = None
        self.debug_mode = debug_mode
        self.output_file = None

        # WEBCAM ONLY: Keep VideoWriter for debug mode (cannot stream-copy raw webcam easily)
        self.video_writer = None

        self.display_width = 854
        self.display_height = 480

        if not self.debug_mode:
            self.create_sdp_file()

    def create_sdp_file(self):
        sdp_content = """v=0
o=- 0 0 IN IP4 127.0.0.1
s=BlueROV Video
c=IN IP4 0.0.0.0
t=0 0
m=video 5602 RTP/AVP 96
a=rtpmap:96 H264/90000
a=fmtp:96 packetization-mode=1;sprop-parameter-sets=Z01AKZZUA8ARPyo=,aO44gA==;profile-level-id=4d4029;level-asymmetry-allowed=1
"""
        if not os.path.exists("config"):
            os.makedirs("config")
        with open(os.path.join("config", "stream.sdp"), "w") as f:
            f.write(sdp_content)

    def start_recording(self, path):
        """
        Enables recording by setting the path and triggering a process restart.
        The restart is necessary to inject the '-c:v copy' argument into FFmpeg.
        """
        self.output_file = path
        self.log_signal.emit(f"[REC] Starting Recording (Stream Copy): {path}")

        if self.debug_mode:
            # Webcam handles recording inside its loop without restart
            pass
        else:
            # FFmpeg needs restart to add the file output output
            self.restart_requested = True
            if self.process:
                self.process.terminate()  # Force the read-loop to break

    def stop_recording(self):
        """
        Disables recording and triggers a process restart to stop writing to disk.
        """
        self.log_signal.emit("[REC] Stopping Recording.")
        self.output_file = None

        if self.debug_mode:
            if self.video_writer:
                self.video_writer.release()
                self.video_writer = None
        else:
            self.restart_requested = True
            # --- USE GRACEFUL STOP TO SAVE METADATA ---
            self.graceful_ffmpeg_stop()

    def graceful_ffmpeg_stop(self):
        """
        Sends 'q' to FFmpeg's stdin to allow it to write the file trailer/metadata
        before exiting. Falls back to terminate() if it hangs.
        """
        if self.process and self.process.poll() is None:
            try:
                # Send 'q' to quit cleanly
                if self.process.stdin:
                    self.process.stdin.write(b'q')
                    self.process.stdin.flush()
                
                # Wait up to 2 seconds for FFmpeg to write the trailer
                self.process.wait(timeout=2.0)
                self.log_signal.emit("[FFMPEG] Closed cleanly (Metadata saved).")
            except Exception as e:
                self.log_signal.emit(f"[FFMPEG] Graceful stop failed ({e}), forcing kill.")
                self.process.terminate()

    def run(self):
        """
        Main Thread Loop.
        It keeps the video running even if the underlying FFmpeg process
        needs to restart (e.g., to toggle recording).
        """
        while self.run_flag:
            if self.debug_mode:
                self.run_debug_webcam()
                # Webcam loop is blocking, so if it exits, we stop completely
                break
            else:
                self.restart_requested = False
                self.run_ffmpeg_udp()

                # If we are here, run_ffmpeg_udp finished.
                # If it finished because of a restart request, we loop again.
                # If it finished because run_flag is False, we exit.
                if not self.restart_requested:
                    break

    def run_debug_webcam(self):
        self.log_signal.emit("[DEBUG] Main Cam (Webcam) Active")
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            self.log_signal.emit("[ERR] Failed to open Webcam 0!")
            return

        cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        while self.run_flag:
            ret, frame = cap.read()
            if not ret:
                self.msleep(100)
                continue

            # Webcam recording (CPU intensive, but only for debug)
            if self.output_file:
                if self.video_writer is None:
                    fourcc = cv2.VideoWriter_fourcc(*'XVID')
                    self.video_writer = cv2.VideoWriter(self.output_file, fourcc, 20.0, (cam_w, cam_h))

                if self.video_writer.isOpened():
                    self.video_writer.write(frame)

            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            qt_image = QImage(rgb_image.data, cam_w, cam_h, cam_w * 3, QImage.Format.Format_RGB888).copy()
            self.change_pixmap_signal.emit(qt_image)
            self.msleep(30)

        cap.release()
        if self.video_writer:
            self.video_writer.release()
        self.log_signal.emit("[DEBUG] Camera Closed.")

    def run_ffmpeg_udp(self):
        ffmpeg_bin = './bin/ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
        sdp_path = os.path.join("config", "stream.sdp")

        # Base Command (Inputs and Flags)
        cmd = [
            ffmpeg_bin, '-y',
            '-hide_banner',
            '-loglevel', 'warning',
            '-protocol_whitelist', 'file,udp,rtp',
            '-fflags', 'discardcorrupt',
            '-flags', 'low_delay',
            '-reorder_queue_size', '1000',
            '-max_delay', '50000',
            '-strict', 'experimental',
            '-i', sdp_path
        ]

        # OPTIONAL: Stream Copy to Disk (The Efficient Method)
        if self.output_file:
            cmd.extend(['-c:v', 'copy', self.output_file])

        # ALWAYS: Pipe to Python (Display)
        # Note: We reset codec to rawvideo for the pipe output
        cmd.extend([
            '-f', 'image2pipe',
            '-pix_fmt', 'bgr24',
            '-vcodec', 'rawvideo',
            '-s', f'{self.display_width}x{self.display_height}',
            '-'
        ])

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        mode_str = "RECORDING" if self.output_file else "PREVIEW"
        self.log_signal.emit(f"[FFMPEG] Starting Stream ({mode_str})...")

        try:
            # --- FIX: ADD stdin=subprocess.PIPE ---
            self.process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,  # <--- Essential for sending 'q'
                bufsize=10 ** 8, 
                startupinfo=startupinfo
            )
        except FileNotFoundError:
            self.log_signal.emit(f"[ERR] FFmpeg not found at {ffmpeg_bin}")
            return

        # Start stderr reader in background
        self.error_reader_thread = threading.Thread(target=self.read_stderr)
        self.error_reader_thread.daemon = True
        self.error_reader_thread.start()

        frame_size = self.display_width * self.display_height * 3

        # Read Loop
        while self.run_flag and not self.restart_requested:
            try:
                in_bytes = bytearray()
                while len(in_bytes) < frame_size and self.run_flag and not self.restart_requested:
                    bytes_needed = frame_size - len(in_bytes)
                    chunk = self.process.stdout.read(bytes_needed)
                    if not chunk: break
                    in_bytes.extend(chunk)

                if len(in_bytes) != frame_size:
                    if len(in_bytes) == 0: self.msleep(10)
                    continue

                # We don't write to disk here anymore. FFmpeg handles it.
                # We just decode for display.
                frame = np.frombuffer(in_bytes, np.uint8).reshape((self.display_height, self.display_width, 3))
                rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                # .copy() is crucial to prevent crash when resizing window
                qt_image = QImage(rgb_image.data, self.display_width, self.display_height,
                                  self.display_width * 3, QImage.Format.Format_RGB888).copy()
                self.change_pixmap_signal.emit(qt_image)

            except Exception as e:
                # If we are restarting, a pipe error is expected (we killed the process)
                if not self.restart_requested:
                    self.log_signal.emit(f"[PY] Pipe Error: {e}")
                break

        # Cleanup subprocess
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def read_stderr(self):
        while self.process and self.process.poll() is None:
            try:
                line = self.process.stderr.readline()
                if line:
                    decoded = line.decode('utf-8', errors='ignore').strip()
                    if "frame=" not in decoded and decoded:
                        print(f"[FFMPEG] {decoded}")
            except:
                break

    def stop(self):
        self.run_flag = False
        self.restart_requested = False
        self.graceful_ffmpeg_stop()
        self.wait()