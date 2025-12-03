import cv2
import socket
import numpy as np

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QImage


class VideoThreadUDP(QThread):
    change_pixmap_signal = pyqtSignal(QImage)

    def __init__(self, port, name="Unknown"):
        super().__init__()
        self.port = port
        self.name = name
        self.run_flag = True
        self.sock = None

    def run(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(('0.0.0.0', self.port))
            self.sock.settimeout(0.5)
        except Exception:
            return

        while self.run_flag:
            try:
                data, addr = self.sock.recvfrom(65535)
                np_arr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if frame is not None:
                    rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w

                    # FIX: Added .copy() to decouple QImage from the temporary numpy array
                    qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format.Format_RGB888).copy()

                    self.change_pixmap_signal.emit(qt_image)
            except socket.timeout:
                continue
            except Exception:
                pass
        self.sock.close()

    def stop(self):
        self.run_flag = False
        self.wait()