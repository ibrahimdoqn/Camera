"""Apple-inspired QSS for a modern, clean look."""
from __future__ import annotations

# Color palette inspired by macOS Sonoma / Ventura dark appearance.
COLORS = {
    "bg":            "#1c1c1e",
    "bg_elevated":   "#2c2c2e",
    "bg_hover":      "#3a3a3c",
    "border":        "#3a3a3c",
    "text":          "#f2f2f7",
    "text_muted":    "#9a9aa0",
    "accent":        "#0a84ff",
    "accent_hover":  "#3a9bff",
    "danger":        "#ff453a",
    "success":       "#30d158",
}

APP_STYLESHEET = f"""
* {{
    color: {COLORS['text']};
    font-family: "SF Pro Display", "Inter", "Segoe UI Variable", "Segoe UI", sans-serif;
}}

QMainWindow, QDialog {{
    background-color: {COLORS['bg']};
}}

QWidget#Sidebar {{
    background-color: {COLORS['bg_elevated']};
    border-right: 1px solid {COLORS['border']};
}}

QLabel#TitleLabel {{
    font-size: 18px;
    font-weight: 600;
    padding: 4px 2px;
}}

QLabel#SectionLabel {{
    font-size: 11px;
    font-weight: 600;
    color: {COLORS['text_muted']};
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 8px 2px 4px 2px;
}}

QLabel#MutedLabel {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}

QPushButton {{
    background-color: {COLORS['bg_hover']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
}}
QPushButton:hover {{
    background-color: #48484a;
}}
QPushButton:pressed {{
    background-color: #5a5a5c;
}}
QPushButton:disabled {{
    color: {COLORS['text_muted']};
    background-color: #2a2a2c;
}}

QPushButton#PrimaryButton {{
    background-color: {COLORS['accent']};
    border: none;
    color: white;
    font-weight: 600;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton#DangerButton {{
    background-color: transparent;
    border: 1px solid {COLORS['danger']};
    color: {COLORS['danger']};
}}
QPushButton#DangerButton:hover {{
    background-color: rgba(255, 69, 58, 0.18);
}}

QPushButton#IconButton {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    color: {COLORS['text_muted']};
    font-size: 16px;
}}
QPushButton#IconButton:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text']};
}}

QPushButton#ToggleButton {{
    background-color: {COLORS['bg']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    color: {COLORS['text']};
    font-size: 24px;
    font-weight: 900;
    padding: 0 0 3px 0;
}}
QPushButton#ToggleButton:hover {{
    background-color: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
    color: white;
}}
QPushButton#ToggleButton:pressed {{
    background-color: {COLORS['accent_hover']};
}}

QPushButton#MuteButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 0;
    font-size: 14px;
}}
QPushButton#MuteButton:hover {{
    background-color: {COLORS['bg_hover']};
}}
QPushButton#MuteButton:checked {{
    color: {COLORS['accent']};
}}

/* Inside a selected (blue) row, the mute toggle & dot must remain visible. */
QWidget#CameraRow[selected="true"] QPushButton#MuteButton {{
    color: white;
    background-color: rgba(255, 255, 255, 0.18);
}}
QWidget#CameraRow[selected="true"] QPushButton#MuteButton:hover {{
    background-color: rgba(255, 255, 255, 0.30);
}}
QWidget#CameraRow[selected="true"] QPushButton#MuteButton:checked {{
    color: white;
    background-color: rgba(255, 255, 255, 0.28);
}}

QPushButton#PtzButton {{
    background-color: {COLORS['bg']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 4px;
    font-size: 14px;
    font-weight: 600;
}}
QPushButton#PtzButton:hover {{
    background-color: {COLORS['bg_hover']};
    border: 1px solid {COLORS['accent']};
}}
QPushButton#PtzButton:pressed {{
    background-color: {COLORS['accent']};
    color: white;
    border: 1px solid {COLORS['accent']};
}}
QPushButton#PtzButton:disabled {{
    color: {COLORS['text_muted']};
    background-color: #2a2a2c;
    border: 1px solid #333335;
}}

QFrame#Separator {{
    background-color: {COLORS['border']};
    border: none;
    max-height: 1px;
}}

QListWidget {{
    background-color: transparent;
    border: none;
    outline: 0;
    padding: 4px;
}}
QListWidget::item {{
    background-color: transparent;
    color: {COLORS['text']};
    border: none;
    padding: 0;
    margin: 0;
}}
QListWidget::item:hover,
QListWidget::item:selected {{
    background-color: transparent;
}}

/* Selection / hover are painted by CameraRow itself. */
QListWidget#CameraList {{
    padding: 4px 6px;
}}

QWidget#CameraRow {{
    background-color: transparent;
    border-radius: 10px;
}}
QWidget#CameraRow:hover {{
    background-color: {COLORS['bg_hover']};
}}
QWidget#CameraRow[selected="true"] {{
    background-color: {COLORS['accent']};
}}
QWidget#CameraRow[selected="true"]:hover {{
    background-color: {COLORS['accent_hover']};
}}

QLabel#CameraDot {{
    background-color: {COLORS['success']};
    border-radius: 5px;
    min-width: 10px;
    max-width: 10px;
    min-height: 10px;
    max-height: 10px;
}}
/* Keep the green dot visible inside the selected (blue) row by giving it a
   subtle white halo, but don't strip its status colour. */
QWidget#CameraRow[selected="true"] QLabel#CameraDot {{
    border: 2px solid white;
}}

QLabel#CameraRowName {{
    color: {COLORS['text']};
    font-size: 14px;
    font-weight: 600;
    background: transparent;
}}
QWidget#CameraRow[selected="true"] QLabel#CameraRowName {{
    color: white;
}}

QLabel#CameraRowSub {{
    color: {COLORS['text_muted']};
    font-size: 11px;
    background: transparent;
}}
QWidget#CameraRow[selected="true"] QLabel#CameraRowSub {{
    color: rgba(255, 255, 255, 0.95);
}}

QLineEdit, QSpinBox, QComboBox {{
    background-color: {COLORS['bg']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 10px;
    selection-background-color: {COLORS['accent']};
    font-size: 13px;
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 1px solid {COLORS['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_elevated']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    selection-background-color: {COLORS['accent']};
    padding: 4px;
}}

QCheckBox {{
    spacing: 8px;
    font-size: 13px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1px solid {COLORS['border']};
    background: {COLORS['bg']};
}}
QCheckBox::indicator:checked {{
    background: {COLORS['accent']};
    border: 1px solid {COLORS['accent']};
}}

QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: #4a4a4c;
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: #5a5a5c;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QStatusBar {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text_muted']};
    border-top: 1px solid {COLORS['border']};
}}

QLabel#ResourceLabel {{
    color: {COLORS['text_muted']};
    font-size: 12px;
}}

QLabel#PtzCameraName {{
    color: {COLORS['text']};
    font-size: 13px;
    font-weight: 600;
    padding: 0 4px;
}}

QToolTip {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text']};
    border: 1px solid {COLORS['border']};
    padding: 6px 8px;
    border-radius: 6px;
}}
"""
