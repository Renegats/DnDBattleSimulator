import json
import os
import tkinter as tk
from tkinter import ttk
from ui_components import RoundedButton

THEME_FILE = os.path.join('battle_settings', 'theme.json')

THEMES = {
    'dark': {   # Тёмная тема
        'bg': '#36393f',
        'bg_secondary': '#2f3136',
        'field_bg': '#40444b',
        'fg': '#dcddde',
        'fg_muted': '#96989d',
        'accent': '#5865f2',
        'button_bg': '#40444b',
        'button_fg': '#dcddde',
        'border': '#202225',
        'canvas_map': '#2b2d31',
        'canvas_grid': '#383b40',
        'canvas_reach': '#3a463a',
        'icon': '🌙',
        'hover': '#40444b',
    },
    'light': {  # Светлая тема: тёплый пергамент
        'bg': '#f2ede3',
        'bg_secondary': '#e8e1d3',
        'field_bg': '#faf7f0',
        'fg': '#33302a',
        'fg_muted': '#8a8177',
        'accent': '#a8763e',
        'button_bg': '#e3dbc9',
        'button_fg': '#33302a',
        'border': '#d5cbb8',
        'canvas_map': '#e6dfcd',
        'canvas_grid': '#cfc4aa',
        'canvas_reach': '#cddcae',
        'icon': '☀️',
        'hover': '#ddd2bc',
    },
}


def current_palette(obj):
    """Палитра текущей темы для любого объекта, у которого есть theme_manager"""
    tm = getattr(obj, 'theme_manager', None)
    return THEMES.get(getattr(tm, 'current', 'dark'))


class ThemeManager:
    """Применяет палитру ко всем ttk-виджетам через Style"""

    def __init__(self, root):
        self.root = root
        self.style = ttk.Style(root)
        try:
            self.style.theme_use('clam')  # clam умеет перекрашиваться целиком
        except tk.TclError:
            pass
        self.current = self._load_saved() or 'dark'

    def _load_saved(self):
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

    def apply(self, theme_name=None):
        if theme_name in THEMES:
            self.current = theme_name
        p = self.palette()
        s = self.style
        self.root.configure(bg=p['bg'])

        s.configure('.', background=p['bg'], foreground=p['fg'],
                    fieldbackground=p['field_bg'], bordercolor=p['border'],
                    lightcolor=p['border'], darkcolor=p['border'],
                    troughcolor=p['bg_secondary'],
                    selectbackground=p['accent'], selectforeground='#ffffff')
        s.configure('TFrame', background=p['bg'])
        s.configure('TLabel', background=p['bg'], foreground=p['fg'])
        s.configure('TLabelframe', background=p['bg'], bordercolor=p['border'])
        s.configure('TLabelframe.Label', background=p['bg'], foreground=p['fg'])
        s.configure('TButton', background=p['button_bg'], foreground=p['button_fg'],
                    bordercolor=p['border'], padding=(8, 4))
        s.map('TButton',
              background=[('active', p['accent']), ('pressed', p['accent'])],
              foreground=[('active', '#ffffff')])
        s.configure('TEntry', fieldbackground=p['field_bg'], foreground=p['fg'],
                    insertcolor=p['fg'], bordercolor=p['border'])
        s.configure('TCombobox', fieldbackground=p['field_bg'], foreground=p['fg'],
                    bordercolor=p['border'], arrowcolor=p['fg_muted'])
        s.map('TCombobox',
              fieldbackground=[('readonly', p['button_bg'])],
              foreground=[('readonly', p['button_fg'])])
        s.configure('TSpinbox', fieldbackground=p['field_bg'], foreground=p['fg'],
                    bordercolor=p['border'], arrowcolor=p['fg'])
        s.configure('TCheckbutton', background=p['bg'], foreground=p['fg'])
        s.map('TCheckbutton', background=[('active', p['bg'])])
        s.configure('TRadiobutton', background=p['bg'], foreground=p['fg'])
        s.map('TNotebook.Tab',
              background=[('selected', p['bg'])],
              foreground=[('selected', p['accent'])])
        for orient in ('Vertical', 'Horizontal'):
            s.configure(f'{orient}.Scrollbar', background=p['button_bg'],
                        troughcolor=p['bg_secondary'], bordercolor=p['border'],
                        arrowcolor=p['fg'])
            s.map(f'{orient}.Scrollbar', background=[('active', p['accent'])])

        # Дефолты для "голых" Tk-виджетов, которые создадутся ПОСЛЕ применения
        self.root.option_add('*Canvas.background', p['bg'])
        self.root.option_add('*Canvas.highlightThickness', 0)
        self.root.option_add('*Listbox.background', p['field_bg'])
        self.root.option_add('*Listbox.foreground', p['fg'])
        self.root.option_add('*Listbox.selectBackground', p['accent'])
        self.root.option_add('*Listbox.selectForeground', '#ffffff')
        self.root.option_add('*Text.background', p['field_bg'])
        self.root.option_add('*Text.foreground', p['fg'])
        self.root.option_add('*Text.insertBackground', p['fg'])
        self.root.option_add('*TCombobox*Listbox.background', p['field_bg'])
        self.root.option_add('*TCombobox*Listbox.foreground', p['fg'])
        self.root.option_add('*TCombobox*Listbox.selectBackground', p['accent'])
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')


class ThemeUI:
    """Кнопка-переключатель темы"""

    def __init__(self):
        self.theme_btn = None

    def setup_theme_button(self, master):
        p = self.theme_manager.palette()
        self.theme_btn = RoundedButton(
            master, command=self.toggle_theme, palette=p,
            width=42, height=34, radius=10,
            icon='moon' if self.theme_manager.current == 'dark' else 'sun')
        self.theme_btn.pack(side='right', padx=10)

    def toggle_theme(self):
        new = 'light' if self.theme_manager.current == 'dark' else 'dark'
        self.theme_manager.apply(new)
        self.theme_manager.save()
        self.theme_btn.set_icon('moon' if new == 'dark' else 'sun')
        self._retint_all(self.root)
        if getattr(self, 'battle_map', None) and getattr(self, 'map_canvas', None):
            self.draw_map()

    def _retint_all(self, widget):
        """Рекурсивно перекрашивает голые Tk-виджеты и закруглённые кнопки"""
        p = self.theme_manager.palette()
        for w in widget.winfo_children():
            cls = w.winfo_class()
            try:
                if w is getattr(self, 'sub_bar', None):
                    w.configure(bg=p['bg_secondary'])
                elif w is getattr(self, 'sub_sep', None):
                    w.configure(bg=p['border'])
                elif w is getattr(self, 'sub_caption', None):
                    w.configure(bg=p['bg_secondary'], fg=p['fg_muted'])
                elif isinstance(w, RoundedButton):
                    w.apply_palette(p)
                elif cls == 'Canvas':
                    if w is getattr(self, 'map_canvas', None):
                        w.configure(bg=p['canvas_map'], highlightbackground=p['border'])
                    else:
                        w.configure(bg=p['bg'])
                elif cls == 'Text':
                    w.configure(bg=p['field_bg'], fg=p['fg'],
                                insertbackground=p['fg'], selectbackground=p['accent'])
                elif cls == 'Listbox':
                    w.configure(bg=p['field_bg'], fg=p['fg'],
                                selectbackground=p['accent'],
                                highlightbackground=p['border'])
                elif cls == 'Button' and not isinstance(w, ttk.Button):
                    w.configure(bg=p['button_bg'], fg=p['button_fg'],
                                activebackground=p['accent'], activeforeground='#ffffff')
                elif cls == 'Frame' and not isinstance(w, ttk.Frame):
                    w.configure(bg=p['bg'])
                elif cls == 'Label' and not isinstance(w, ttk.Label):
                    w.configure(bg=p['bg'], fg=p['fg'])
            except tk.TclError:
                pass
            self._retint_all(w)