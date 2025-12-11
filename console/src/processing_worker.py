import os
import glob
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal

class ProcessingWorker(QThread):
    # Signal: (success, status_message, output_file_path)
    finished_signal = pyqtSignal(bool, str, str)

    def __init__(self, executable, images_dir):
        super().__init__()
        self.executable = executable
        self.images_dir = images_dir

    def run(self):
        # 1. Find the latest file (Performed in background thread now)
        if not os.path.exists(self.images_dir):
            self.finished_signal.emit(False, f"Dir not found: {self.images_dir}", "")
            return

        # Get list of .jpg files
        list_of_files = glob.glob(os.path.join(self.images_dir, "*.jpg"))
        if not list_of_files:
            self.finished_signal.emit(False, "No images found to process", "")
            return

        # Find latest by creation time
        try:
            latest_file = max(list_of_files, key=os.path.getctime)
        except Exception as e:
            self.finished_signal.emit(False, f"Error finding latest file: {e}", "")
            return

        # 2. Prepare Output Path
        filename = os.path.basename(latest_file)
        output_filename = f"processed_{filename}"
        output_path = os.path.join(self.images_dir, output_filename)

        # 3. Check Executable
        if not os.path.exists(self.executable):
            self.finished_signal.emit(False, f"Executable not found: {self.executable}", "")
            return

        # 4. Run Processing
        try:
            # We use subprocess.run here because we are already in a background thread,
            # so blocking THIS thread is fine (and safe).
            result = subprocess.run(
                [self.executable, latest_file, output_path],
                capture_output=True,
                text=True
            )

            if result.returncode == 0:
                self.finished_signal.emit(True, f"Processed: {filename}", output_path)
            else:
                self.finished_signal.emit(False, f"Process Failed: {result.stderr}", "")
        except Exception as e:
            self.finished_signal.emit(False, f"Execution Error: {str(e)}", "")