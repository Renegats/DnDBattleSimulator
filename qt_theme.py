"""Темы Qt-фронтенда: порт theme_manager.py на QSS.

Палитры 1:1 из Tkinter-версии, файл темы общий (battle_settings/theme.json),
поэтому переключение в любом фронтенде видно в обоих.
"""
import json
import os
from string import Template

THEME_FILE = os.path.join('battle_settings', 'theme.json')

THEMES = {
    'dark': {
        'bg': '#36393f', 'bg_secondary': '#2f3136', 'field_bg': '#40444b',
        'fg': '#dcddde', 'fg_muted': '#96989d', 'accent': '#5865f2',
        'button_bg': '#40444b', 'button_fg': '#dcddde', 'border': '#202225',
        'canvas_map': '#2b2d31', 'canvas_grid': '#383b40', 'canvas_reach': '#3a463a',
        'hover': '#4a4d55', 'icon': '🌙',
        'danger': '#e74c3c', 'success': '#2ecc71', 'warning': '#f1c40f',
    },
    'light': {
        'bg': '#f2ede3', 'bg_secondary': '#e8e1d3', 'field_bg': '#faf7f0',
        'fg': '#33302a', 'fg_muted': '#8a8177', 'accent': '#a8763e',
        'button_bg': '#e3dbc9', 'button_fg': '#33302a', 'border': '#d5cbb8',
        'canvas_map': '#e6dfcd', 'canvas_grid': '#cfc4aa', 'canvas_reach': '#cddcae',
        'hover': '#ddd2bc', 'icon': '☀️',
        'danger': '#c0392b', 'success': '#4a7c3f', 'warning': '#b8860b',
    },
}

_QSS = Template("""
* { font-family: 'Segoe UI'; font-size: 10pt; outline: none; }
QWidget { background: $bg; color: $fg; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: $fg_muted; }
QLabel[role="title"] { font-size: 11pt; font-weight: bold; }
QLabel[role="accent"] { color: $accent; font-weight: bold; }
QFrame[role="card"] { background: $bg_secondary; border: 1px solid $border; border-radius: 12px; }
QFrame[role="bar"] { background: $bg_secondary; border: none; }
QFrame[role="sep"] { background: $border; max-height: 2px; }

QPushButton { background: $button_bg; color: $button_fg; border: 1px solid $border;
              border-radius: 10px; padding: 6px 14px; }
QPushButton:hover { background: $hover; border-color: $accent; }
QPushButton:pressed { background: $accent; color: #ffffff; }
QPushButton:checked { background: $accent; color: #ffffff; border-color: $accent; font-weight: bold; }
QPushButton:disabled { color: $fg_muted; border-color: $border; }
QPushButton[variant="outline"] { background: transparent; color: $fg_muted; }
QPushButton[variant="outline"]:hover { color: $accent; border-color: $accent; }
QPushButton[variant="danger"] { background: transparent; color: $danger; border-color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger; color: #ffffff; }
QPushButton[variant="flat"] { background: transparent; border: none; color: $fg_muted; padding: 2px 6px; }
QPushButton[variant="flat"]:hover { color: $danger; }

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {
    background: $field_bg; color: $fg; border: 1px solid $border;
    border-radius: 6px; padding: 3px 6px;
    selection-background-color: $accent; selection-color: #ffffff; }
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: $accent; }
QLineEdit[role="title"] { background: transparent; border: none; font-size: 11pt;
                          font-weight: bold; color: $accent; padding: 0; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox::down-arrow { image: none; border-left: 4px solid transparent;
    border-right: 4px solid transparent; border-top: 5px solid $fg_muted; margin-right: 6px; }
QComboBox QAbstractItemView { background: $field_bg; color: $fg; border: 1px solid $border;
    selection-background-color: $accent; selection-color: #ffffff; }
QSpinBox::up-button, QSpinBox::down-button { background: $button_bg; width: 14px; border: none; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: $accent; }

QCheckBox { spacing: 6px; background: transparent; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid $border;
                       border-radius: 4px; background: $field_bg; }
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }

QGroupBox { background: $bg_secondary; border: 1px solid $border; border-radius: 12px;
            margin-top: 14px; padding: 10px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px;
                   color: $accent; font-weight: bold; }

QToolButton { background: transparent; border: none; color: $fg; padding: 2px; }
QToolButton:hover { color: $accent; }

QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: $bg_secondary; width: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:vertical { background: $button_bg; border-radius: 6px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $accent; }
QScrollBar:horizontal { background: $bg_secondary; height: 12px; margin: 0; border-radius: 6px; }
QScrollBar::handle:horizontal { background: $button_bg; border-radius: 6px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: $accent; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }

QHeaderView::section { background: $bg_secondary; color: $fg_muted; border: none;
                       padding: 4px; font-weight: bold; }
QTableWidget { gridline-color: $border; }
QTableWidget::item { padding: 2px 4px; }
QListWidget::item { padding: 3px 4px; border-radius: 4px; }
QListWidget::item:selected { background: $accent; color: #ffffff; }
QToolTip { background: $field_bg; color: $fg; border: 1px solid $accent; padding: 4px; }
QStatusBar { background: $bg_secondary; color: $fg_muted; }
""")


class QtTheme:
    """Применяет палитру ко всему приложению одной строкой QSS."""

    def __init__(self, app):
        self.app = app
        self.current = self._load() or 'dark'
        self.apply()

    @staticmethod
    def _load():
        try:
            with open(THEME_FILE, 'r', encoding='utf-8') as f:
                return json.load(f).get('theme')
        except Exception:
            return None

    def save(self):
        try:
            os.makedirs('battle_settings', exist_ok=True)
            with open(THEME_FILE, 'w', encoding='utf-8') as f:
                json.dump({'theme': self.current}, f)
        except Exception:
            pass

    def palette(self):
        return THEMES[self.current]

    def apply(self, name=None):
        if name in THEMES:
            self.current = name
        self.app.setStyleSheet(_QSS.substitute(self.palette()))

    def toggle(self):
        self.apply('light' if self.current == 'dark' else 'dark')
        self.save()
        return self.current

def current_palette():
    """Палитра активной темы для диалогов, у которых нет ссылки на QtTheme.

    Читает тот же battle_settings/theme.json, что и QtTheme, поэтому диалог
    импорта всегда в той же теме, что и главное окно. Самодостаточна: зависит
    только от THEMES/THEME_FILE/json этого модуля.
    """
    name = 'dark'
    try:
        with open(THEME_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f).get('theme')
        if saved in THEMES:
            name = saved
    except Exception:
        pass
    return THEMES[name]