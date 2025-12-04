import os
import subprocess
from PyQt6.QtCore import QThread, pyqtSignal


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