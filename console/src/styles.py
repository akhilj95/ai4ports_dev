MISSION_BOX = """
    QGroupBox { 
        font-weight: bold; border: 1px solid #444; background-color: #222; 
        margin-top: 6px; padding-top: 5px; 
    }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
"""

INPUT_FIELD = "padding: 5px; color: white; background-color: #333; border: 1px solid #555; font-size: 13px;"

BTN_CREATE = """
    QPushButton {
        background-color: #2196F3; color: white; font-weight: bold; padding: 5px 15px; 
        font-size: 13px; border-radius: 4px; border: 1px solid #1976D2;
    }
    QPushButton:hover { background-color: #42A5F5; }
"""

BTN_FINISH = """
    QPushButton {
        background-color: #C62828; color: white; font-weight: bold; padding: 5px 15px; 
        font-size: 13px; border-radius: 4px; border: 1px solid #B71C1C;
    }
    QPushButton:hover { background-color: #E53935; }
"""

BTN_START = """
    QPushButton { background-color: #2E7D32; color: white; border: 1px solid #1B5E20; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px; } 
    QPushButton:hover { background-color: #388E3C; }
"""

BTN_STOP = """
    QPushButton { background-color: #C62828; color: white; border: 1px solid #B71C1C; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px; } 
    QPushButton:hover { background-color: #D32F2F; } 
    QPushButton:disabled { background-color: #444; color: #888; border: 1px solid #333; }
"""

BTN_PROCESS = """
    QPushButton { background-color: #1565C0; color: white; border: 1px solid #0D47A1; font-weight: bold; font-size: 14px; padding: 10px; border-radius: 6px; } 
    QPushButton:hover { background-color: #1976D2; } 
    QPushButton:disabled { background-color: #444; color: #888; border: 1px solid #333; }
"""

VIDEO_LABEL = "background-color: #111; color: #555; border: 1px solid #333;"

LOG_OUTPUT = "background-color: #000; color: #0f0; font-family: Consolas; border: 1px solid #444; font-size: 11px;"

SLIDER_STYLE = """
    QSlider::groove:horizontal { height: 6px; background: #555; border-radius: 3px; }
    QSlider::handle:horizontal { background: #2196F3; width: 14px; height: 14px; margin: -4px 0; border-radius: 7px; }
"""