"""Qt-фронтенд симулятора: карта в центре, тулбар и прячущаяся панель.

Редкие правила — в диалоге «Настройки боя». Шаблоны отрядов — в немодальном
окне «Стороны». Существо правится карточкой с карты и из списка участников.
"""
import json
import os
import random
import sys
from datetime import datetime

from PyQt6.QtCore import QSettings, QSize, Qt, QEventLoop, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPixmap, QShortcut
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QLineEdit, QSpinBox,
                             QComboBox, QPushButton, QCheckBox,
                             QScrollArea, QStackedWidget, QGroupBox, QFrame,
                             QMessageBox, QFileDialog, QDialog, QTableWidget,
                             QTableWidgetItem, QHeaderView, QSlider,
                             QMenu, QDockWidget, QToolBar, QToolButton, QTabWidget,
                             QButtonGroup, QInputDialog,
                             QListWidget, QListWidgetItem, QSizePolicy)

from qt_icons import tool_icon

import battle_round
from battle_history import BattleHistory, apply_snapshot, capture_battle, ensure_uid
from combat_core import normalize_crit_mode
from combat_log import dump_log, map_marks, render_log
from decision_engine import DecisionEngine
from factory import EnemyFactory
from observer import Observer
from qt_theme import QtTheme
from qt_map_view import MapView, DEFAULT_OPTS, SIDE_PALETTES, BG_MODES
from qt_combat_log import CombatLogPanel
from qt_widgets import IconButton, PortraitCard
import qt_async
import portraits
from qt_editors import SideCreatorDialog, Section, STRATS, make_strategy
from qt_creature_sheet import AddCreatureDialog, CreatureSheet

from battle_map_model import BattleMap

MAX_SIDES = 26
SETTINGS_ORG = 'Renegats'
SETTINGS_APP = 'DnDBattleSimulator'


def types_available():
    return list(EnemyFactory.CREATURE_DEFS) + list(EnemyFactory.CUSTOM_TYPES)


def clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)
            w.deleteLater()
        elif it.layout() is not None:
            clear_layout(it.layout())


class Updater(Observer):
    def __init__(self, win):
        self.win = win

    def update(self, subject):
        self.win.dirty.add(subject)
        if not self.win.suspend:
            self.win.refresh_dirty()


class CardsHost(QWidget):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.grid = QGridLayout(self)
        self.grid.setSpacing(10)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.owner.relayout_cards()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Мастер Подземелий — Симулятор Битв')
        self.resize(1500, 880)
        self.setMinimumSize(960, 600)

        self.theme = QtTheme(QApplication.instance())
        self.engine = DecisionEngine()
        self.updater = Updater(self)
        self.sides, self.side_names, self.ignore_sides = [], [], {}
        self.alliance_settings = []
        self.battle_map = None
        self.battle_events = []
        self.round_no = 0
        self.selected = None
        self.selection = []
        self._keep_group = None
        self._relocate_group = None
        self._roster_sig = None
        self.side_all_checks = []
        self.cards, self.all_vars = [], []
        self.enemy_labels, self.side_checks = {}, []
        self.dirty, self.suspend = set(), False
        self.cols = 3
        self._icon_buttons = []
        self._tool_icons = []
        self.history = BattleHistory()
        self._manual_loop = None
        self._manual_subjects = set()
        self._manual_choices = []
        self._history_ready = False
        self._suspend_history = False
        self._current = None
        self._round_busy = False
        self._nav_index = 0
        self._relocate = None
        self._sheets = []
        self._terrain_brush = 'wall'
        self._terrain_dirty = False
        self._esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc.setContext(Qt.ShortcutContext.WindowShortcut)
        self._esc.activated.connect(self._on_escape)
        self._auto_timer = QTimer(self)
        self._auto_timer.setInterval(700)
        self._auto_timer.timeout.connect(self._auto_tick)

        self._create_menus()
        self._install_history_controls()
        self._install_batch_menu()
        self._batch_dialog = None

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.stack = QStackedWidget()
        v.addWidget(self.stack)
        self.map_page = self._build_map()
        self.map_page.setObjectName('map_page')
        self.stack.addWidget(self.map_page)

        self.roster_page = self._build_roster()
        self.log_page = self._build_log_tab()
        self._build_settings_dialog()
        self._build_dock()
        self._build_sides_dialog()
        self._build_toolbar()
        self._fill_menus()

        self.status = self.statusBar()
        self._sel_label = QLabel('Выделено: 0')
        self._sel_label.setObjectName('selection_count')
        self.status.addPermanentWidget(self._sel_label)
        self.status.showMessage(
            'Карта — основная сцена. Правый щелчок по клетке добавляет существо, '
            'по токену — открывает карточку.')
        self.add_card()
        self.add_card()
        page = self._restore_layout()
        self.select_tab(page)
        self._refresh_initiative()
        self._current = capture_battle(self)
        self._history_ready = True
        self._sync_history_actions()
        self._sync_auto_buttons()

    # ================= каркас окна =================
    def _create_menus(self):
        bar = self.menuBar()
        self.menu_file = bar.addMenu('Файл')
        self.menu_edit = bar.addMenu('Правка')
        self.menu_battle = bar.addMenu('Бой')
        self.menu_sim = bar.addMenu('Симуляция')
        self.menu_view = bar.addMenu('Вид')

    def _settings(self):
        app = QApplication.instance()
        name = SETTINGS_APP
        if app is not None and app.platformName() == 'offscreen':
            name += '.test'
        return QSettings(SETTINGS_ORG, name)

    def select_tab(self, idx):
        try:
            idx = int(idx)
        except (TypeError, ValueError):
            idx = 0
        if idx not in (0, 1, 2, 3):
            idx = 0
        self._nav_index = idx
        if self.stack.count():
            self.stack.setCurrentIndex(0)
        if idx == 1 and hasattr(self, 'side_tabs'):
            self.side_dock.show()
            self.side_tabs.setCurrentIndex(0)
        if idx == 2 and hasattr(self, 'settings_dialog'):
            self._show_settings('alliances')

    def _tool_button(self, kind, tip, slot, name, checkable=False):
        button = QToolButton()
        button.setObjectName(name)
        button.setAutoRaise(True)
        button.setCheckable(checkable)
        button.setIconSize(QSize(20, 20))
        button.setFixedSize(36, 36)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setToolTip(tip)
        button.setStatusTip(tip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        self._tool_icons.append((button, kind))
        return button

    def _apply_tool_icons(self):
        color = self.theme.palette()['fg']
        for button, kind in self._tool_icons:
            button.setIcon(tool_icon(kind, color))
        self._refresh_tab_icons()

    def _refresh_tab_icons(self):
        tabs = getattr(self, 'side_tabs', None)
        if tabs is None:
            return
        color = self.theme.palette()['fg']
        for index, kind in ((0, 'roster'), (1, 'log'), (2, 'book')):
            if index < tabs.count():
                tabs.setTabIcon(index, tool_icon(kind, color, 18))

    def _build_toolbar(self):
        bar = QToolBar('Бой')
        bar.setObjectName('battle_toolbar')
        bar.setMovable(True)
        bar.setFloatable(True)
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setIconSize(QSize(20, 20))
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.battle_toolbar = bar
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)

        self.armies_btn = self._tool_button(
            'armies', 'Стороны — шаблоны отрядов', self._on_armies_button,
            'armies_button', checkable=True)
        self.create_btn = self._tool_button(
            'create', 'Создать армии', self.create_armies, 'create_button')
        self.round_btn = self._tool_button(
            'next', 'Следующий раунд', self.run_round, 'round_button')
        self.auto_btn = self._tool_button(
            'play', 'Автобой — раунды идут, пока не пауза или конец боя',
            self.start_auto, 'auto_button')
        self.pause_btn = self._tool_button(
            'pause', 'Пауза автобоя', self.pause_auto, 'pause_button')
        self.settings_btn = self._tool_button(
            'settings', 'Настройки боя', self._show_settings, 'settings_button')
        self.terrain_btn = self._tool_button(
            'terrain', 'Рельеф — кисть клеток, протяните по карте',
            self._on_terrain_button, 'terrain_button', checkable=True)
        self.theme_btn = IconButton('moon' if self.theme.current == 'dark' else 'sun',
                                    self.theme.palette(), size=36)
        self.theme_btn.setToolTip('Переключить тему')
        self.theme_btn.setStatusTip('Переключить тему')
        self.theme_btn.clicked.connect(self.toggle_theme)
        self._icon_buttons.append(self.theme_btn)

        for button in (self.armies_btn,):
            bar.addWidget(button)
        bar.addSeparator()
        for button in (self.create_btn, self.round_btn, self.auto_btn, self.pause_btn):
            bar.addWidget(button)
        bar.addSeparator()
        bar.addWidget(self.btn_undo)
        bar.addWidget(self.btn_redo)
        bar.addSeparator()
        bar.addWidget(self.terrain_btn)
        bar.addWidget(self.settings_btn)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        bar.addWidget(spacer)
        bar.addWidget(self.theme_btn)
        self._apply_tool_icons()

    def _on_armies_button(self, checked):
        if checked:
            self.show_sides()
        elif getattr(self, 'sides_dialog', None) is not None:
            self.sides_dialog.hide()

    def _show_settings(self, section=None):
        if section == 'alliances' and hasattr(self, '_sec_alliances'):
            self._sec_alliances.arrow.setChecked(True)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def _save_layout(self):
        settings = self._settings()
        settings.setValue('geometry', self.saveGeometry())
        settings.setValue('windowState', self.saveState())
        if hasattr(self, 'side_tabs'):
            settings.setValue('dockTab', self.side_tabs.currentIndex())
        settings.setValue('page', self._nav_index)
        if getattr(self, 'settings_dialog', None) is not None:
            settings.setValue('settingsGeometry', self.settings_dialog.saveGeometry())
        if getattr(self, 'sides_dialog', None) is not None:
            settings.setValue('sidesGeometry', self.sides_dialog.saveGeometry())

    def _restore_layout(self):
        settings = self._settings()
        geometry = settings.value('geometry')
        if geometry is not None:
            self.restoreGeometry(geometry)
        state = settings.value('windowState')
        if state is not None:
            self.restoreState(state)
        tab = settings.value('dockTab')
        if tab is not None and hasattr(self, 'side_tabs'):
            try:
                self.side_tabs.setCurrentIndex(int(tab))
            except (TypeError, ValueError):
                pass
        dialog_geo = settings.value('settingsGeometry')
        if dialog_geo is not None and getattr(self, 'settings_dialog', None) is not None:
            self.settings_dialog.restoreGeometry(dialog_geo)
        sides_geo = settings.value('sidesGeometry')
        if sides_geo is not None and getattr(self, 'sides_dialog', None) is not None:
            self.sides_dialog.restoreGeometry(sides_geo)
        page = settings.value('page', 0)
        try:
            page = int(page)
        except (TypeError, ValueError):
            page = 0
        return page if page in (0, 1, 2, 3) else 0

    def closeEvent(self, event):
        self.pause_auto()
        if self.isVisible():
            self._save_layout()
        super().closeEvent(event)

    def _menu_action(self, menu, text, slot, name=None, checkable=False, tip=None):
        action = QAction(text, self)
        if name:
            action.setObjectName(name)
        action.setCheckable(checkable)
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        else:
            action.setStatusTip(text)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _fill_menus(self):
        self._menu_action(self.menu_file, 'Сохранить настройки', self.save_settings)
        self._menu_action(self.menu_file, 'Загрузить настройки', self.load_settings)
        self.menu_file.addSeparator()
        self._menu_action(self.menu_file, 'Экспорт журнала', self.export_log)
        self._menu_action(self.menu_file, 'Экспорт карты PNG', self.export_map_png)
        self.menu_file.addSeparator()
        self._menu_action(self.menu_file, 'Выход', self.close)

        self.act_round = self._menu_action(
            self.menu_battle, 'Провести раунд', self.run_round, 'act_round',
            tip='Следующий раунд')
        self.act_auto = self._menu_action(
            self.menu_battle, 'Автобой', self.start_auto, 'act_auto',
            tip='Раунды идут сами, пока не пауза или конец боя')
        self.act_pause = self._menu_action(
            self.menu_battle, 'Пауза', self.pause_auto, 'act_pause',
            tip='Остановить автобой')
        self._menu_action(self.menu_battle, 'Создать армии', self.create_armies)
        self._menu_action(self.menu_battle, 'Стороны…', self.show_sides, 'act_sides')
        self._menu_action(self.menu_battle, 'Добавить сторону', self.add_side, 'act_add_side')
        self._menu_action(self.menu_battle, 'Добавить существо…', self.prompt_add_creature,
                          'act_add_creature')
        self._menu_action(self.menu_battle, 'Очистить поле', self.clear_field, 'act_clear_field')
        self.menu_battle.addSeparator()
        self.act_manual = QAction('Ручное управление', self)
        self.act_manual.setObjectName('act_manual')
        self.act_manual.setCheckable(True)
        self.act_manual.setToolTip(self.manual_toggle.toolTip())
        self.act_manual.setStatusTip(self.manual_toggle.toolTip())
        self.act_manual.toggled.connect(self._on_manual_action)
        self.menu_battle.addAction(self.act_manual)
        scope = self.menu_battle.addMenu('Кого вести вручную')
        self.act_scope_one = QAction('Выбранное существо', self)
        self.act_scope_side = QAction('Сторона выбранного', self)
        scope_group = QActionGroup(self)
        scope_group.setExclusive(True)
        for action, index in ((self.act_scope_one, 0), (self.act_scope_side, 1)):
            action.setCheckable(True)
            scope_group.addAction(action)
            scope.addAction(action)
            action.triggered.connect(lambda _checked=False, i=index: self._set_manual_scope(i))
        self.act_scope_one.setChecked(True)
        self.menu_battle.addSeparator()
        self._menu_action(self.menu_battle, 'Расставить случайно', self.place_random)
        self._menu_action(self.menu_battle, 'Расставить строем', self.place_formation)
        self._menu_action(self.menu_battle, 'Массовое редактирование', self.mass_edit)
        self._menu_action(self.menu_battle, 'Показать статус', self.show_status)
        self._menu_action(self.menu_battle, 'Применить альянсы', self.apply_alliances)
        self.menu_battle.addSeparator()
        self.act_settings = self._menu_action(
            self.menu_battle, 'Настройки боя…', self._show_settings, 'act_settings')

        self._menu_action(self.menu_sim, 'Анализ сражения', self.open_analysis)

        self._menu_action(self.menu_view, 'Стороны…', self.show_sides, 'act_view_sides')
        dock_action = self.side_dock.toggleViewAction()
        dock_action.setText('Панель боя')
        self.menu_view.addAction(dock_action)
        self._menu_action(self.menu_view, 'Участники', lambda: self._show_dock_tab(0))
        select_menu = self.menu_view.addMenu('Выделение')
        select_menu.setObjectName('select_menu')
        select_all = select_menu.addAction('Выделить всех', self.select_all_tokens)
        select_all.setObjectName('select_all')
        select_all.setShortcut(QKeySequence('Ctrl+A'))
        select_all.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.addAction(select_all)
        clear_sel = select_menu.addAction('Снять выделение', self.clear_selection)
        clear_sel.setObjectName('select_none')
        self._side_select_menu = select_menu.addMenu('Выделить сторону')
        self._side_select_menu.setObjectName('select_side_menu')
        self._side_select_menu.aboutToShow.connect(self._fill_side_select_menu)
        self._menu_action(self.menu_view, 'Журнал', lambda: self._show_dock_tab(1))
        self._menu_action(self.menu_view, 'Бестиарий', lambda: self._show_dock_tab(2))
        self.menu_view.addSeparator()
        self.act_terrain = QAction('Рельеф', self)
        self.act_terrain.setObjectName('act_terrain')
        self.act_terrain.setCheckable(True)
        self.act_terrain.setToolTip('Рисовать рельеф на карте')
        self.act_terrain.setStatusTip('Рисовать рельеф на карте')
        self.act_terrain.toggled.connect(self.set_terrain_mode)
        self.menu_view.addAction(self.act_terrain)
        self.act_clear_terrain = self._menu_action(
            self.menu_view, 'Очистить рельеф', self.clear_terrain, 'act_clear_terrain')
        self.menu_view.addSeparator()
        self._menu_action(self.menu_view, 'Переключить тему', self.toggle_theme)
        self._menu_action(self.menu_view, 'Сбросить расположение панелей', self.reset_layout)

    def _show_dock_tab(self, index):
        self.side_dock.show()
        self.side_dock.raise_()
        self.side_tabs.setCurrentIndex(index)

    def reset_layout(self):
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, self.battle_toolbar)
        self.battle_toolbar.show()
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.side_dock)
        self.side_dock.show()
        self.resizeDocks([self.side_dock], [420], Qt.Orientation.Horizontal)
        self.side_tabs.setCurrentIndex(0)
        self.status.showMessage('Расположение панелей сброшено.')

    def _on_manual_action(self, checked):
        if self.manual_toggle.isChecked() != bool(checked):
            self.manual_toggle.setChecked(bool(checked))

    def _set_manual_scope(self, index):
        self.manual_scope.setCurrentIndex(index)

    def _sync_auto_buttons(self):
        running = self._auto_timer.isActive()
        self.auto_btn.setEnabled(not running)
        self.pause_btn.setEnabled(running)
        if hasattr(self, 'act_auto'):
            self.act_auto.setEnabled(not running)
            self.act_pause.setEnabled(running)

    def start_auto(self):
        if not self.sides:
            QMessageBox.warning(self, 'Автобой',
                                'Сначала поставьте существ на карту или создайте армии.')
            return
        if self._auto_timer.isActive():
            return
        self.select_tab(3)
        self._auto_timer.start()
        self._sync_auto_buttons()
        self.status.showMessage('Автобой. Пауза остановит его после текущего раунда.')
        self._auto_tick()

    def pause_auto(self):
        was = self._auto_timer.isActive()
        self._auto_timer.stop()
        self._sync_auto_buttons()
        if was:
            self.status.showMessage('Автобой на паузе.')

    def _auto_tick(self):
        if not self._auto_timer.isActive():
            return
        if self._round_busy or self._manual_loop is not None:
            return
        if not self.sides:
            self.pause_auto()
            return
        self.run_round()

    def _on_bestiary_import(self, name):
        self.status.showMessage(f'Бестиарий: «{name}». Укажите клетку и сторону.')
        self.prompt_add_creature(type_name=name)

    def toggle_theme(self):
        name = self.theme.toggle()
        pal = self.theme.palette()
        self.theme_btn.set_kind('moon' if name == 'dark' else 'sun')
        for b in self._icon_buttons:
            b.set_palette(pal)
        for c in self.cards:
            c['frame'].set_palette(pal)
        self.map_view.set_palette(pal)
        self._apply_tool_icons()
        if getattr(self, 'bestiary', None) is not None:
            self.bestiary.pal = pal
        self.status.showMessage(f'Тема: {"тёмная" if name == "dark" else "светлая"}')

    # ================= отмена / повтор =================
    def _install_history_controls(self):
        edit = self.menu_edit
        self.undo_action = QAction('Отменить', self)
        self.undo_action.setObjectName('undo')
        self.undo_action.setShortcut(QKeySequence('Ctrl+Z'))
        self.undo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.undo_action.triggered.connect(self.do_undo)
        self.redo_action = QAction('Повторить', self)
        self.redo_action.setObjectName('redo')
        self.redo_action.setShortcuts([
            QKeySequence('Ctrl+Shift+Z'),
            QKeySequence('Ctrl+Y'),
        ])
        self.redo_action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        self.redo_action.triggered.connect(self.do_redo)
        edit.addAction(self.undo_action)
        edit.addAction(self.redo_action)
        self.addAction(self.undo_action)
        self.addAction(self.redo_action)

        self.btn_undo = QToolButton()
        self.btn_redo = QToolButton()
        for button, action, kind in ((self.btn_undo, self.undo_action, 'undo'),
                                     (self.btn_redo, self.redo_action, 'redo')):
            button.setObjectName(action.objectName() + '_button')
            button.setAutoRaise(True)
            button.setIconSize(QSize(20, 20))
            button.setFixedSize(36, 36)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action.trigger)
            self._tool_icons.append((button, kind))

    def _sync_history_actions(self):
        undo = self.history.undo_label()
        redo = self.history.redo_label()
        self.undo_action.setEnabled(undo is not None)
        self.redo_action.setEnabled(redo is not None)
        self.undo_action.setText(f'Отменить: {undo}' if undo else 'Отменить')
        self.redo_action.setText(f'Повторить: {redo}' if redo else 'Повторить')
        self.undo_action.setToolTip(self.undo_action.text() if undo else 'Нечего отменять')
        self.redo_action.setToolTip(self.redo_action.text() if redo else 'Нечего повторять')
        self.undo_action.setStatusTip(self.undo_action.toolTip())
        self.redo_action.setStatusTip(self.redo_action.toolTip())
        self.btn_undo.setEnabled(self.undo_action.isEnabled())
        self.btn_redo.setEnabled(self.redo_action.isEnabled())
        self.btn_undo.setToolTip(self.undo_action.toolTip())
        self.btn_redo.setToolTip(self.redo_action.toolTip())

    def _install_batch_menu(self):
        menu = self.menu_sim
        action = QAction('Пакетная симуляция…', self)
        action.setObjectName('batch_sim_action')
        action.triggered.connect(self.open_batch)
        menu.addAction(action)
        self.batch_action = action

    def _forget_batch_dialog(self, *_args):
        self._batch_dialog = None

    def open_batch(self):
        if not self.sides:
            QMessageBox.warning(
                self, 'Пакетная симуляция',
                'Сначала поставьте существ на карту или создайте армии.')
            return
        app = QApplication.instance()
        if app is not None:
            qt_async.install(app)
        dialog = getattr(self, '_batch_dialog', None)
        if dialog is not None:
            try:
                visible = dialog.isVisible()
            except RuntimeError:
                visible = False
                dialog = None
            if dialog is not None and visible:
                dialog.raise_()
                dialog.activateWindow()
                return
        from qt_batch import BatchDialog
        dialog = BatchDialog(
            self, capture_battle(self),
            auto_move=self.auto_move.isChecked(),
            crit_mode=self.crit_mode.currentData() or 'double_all')
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dialog.destroyed.connect(self._forget_batch_dialog)
        self._batch_dialog = dialog
        dialog.show()

    def _commit(self, label):
        if not self._history_ready or self._suspend_history:
            return False
        after = capture_battle(self)
        if not self.history.commit(label, self._current, after):
            return False
        self._current = after
        self._sync_history_actions()
        return True

    def _note_selection(self):
        """Выбор токена не шаг истории, но повтор хода не должен его сбрасывать."""
        if not self._history_ready or self._suspend_history or not self._current:
            return
        uid = ensure_uid(self.selected) if self.selected is not None else None
        uids = [ensure_uid(enemy) for enemy in self.selection if enemy is not None]
        if (self._current.get('selected_uid') == uid
                and self._current.get('selected_uids') == uids):
            return
        snap = dict(self._current)
        snap['selected_uid'] = uid
        snap['selected_uids'] = uids
        self._current = snap

    def _latest_round_events(self):
        numbered = [event for event in self.battle_events if event.round]
        if not numbered:
            return []
        last = max(event.round for event in numbered)
        return [event for event in self.battle_events if event.round == last]

    def _sync_cards(self, rows):
        rows = list(rows or [])
        if len(rows) != len(self.cards):
            self._discard_cards()
            for row in rows:
                self.add_card(row.get('type'), row.get('strategy') or 'случайная',
                              row.get('name'),
                              row.get('count') if row.get('count') is not None else 5)
            return
        for card, row in zip(self.cards, rows):
            card['name'].setText(row.get('name') or '')
            new_type = row.get('type') or card['type']
            changed = new_type != card['type']
            card['type'] = new_type
            card['type_lbl'].setText(new_type)
            card['strat'].blockSignals(True)
            card['strat'].setCurrentText(row.get('strategy') or card['strat'].currentText())
            card['strat'].blockSignals(False)
            card['count'].blockSignals(True)
            card['count'].setValue(int(row.get('count') if row.get('count') is not None else 0))
            card['count'].blockSignals(False)
            if changed:
                self._show_cached_portrait(card)

    def _discard_cards(self):
        for card in list(self.cards):
            card['alive'] = False
            guard = card.get('guard')
            if guard is not None:
                guard.drop()
            for button in card['icons']:
                if button in self._icon_buttons:
                    self._icon_buttons.remove(button)
            card['frame'].setParent(None)
            card['frame'].deleteLater()
        self.cards = []
        self.cols = 0

    def _restore(self, snapshot):
        self._suspend_history = True
        try:
            info = apply_snapshot(snapshot, self)
            self._sync_cards(snapshot.get('setup') or [])
            if info.roster_changed:
                self.rebuild_battle_lists()
                self.log_panel.set_roster(self.sides, self.side_names)
            else:
                self.refresh_all_labels()
            self.refresh_alliances()
            if info.events_changed:
                self.log_panel.load_events(self.battle_events)
            self.selected = info.selected
            self.selection = [enemy for enemy in (info.selection or []) if self._holds(enemy)]
            if self.selected is not None and self.selected not in self.selection:
                self.selection.append(self.selected)
            self.map_view.rebuild(self.battle_map, self.sides, self.selected, self.selection)
            self._sync_checks()
            if self._sel_label is not None:
                self._sel_label.setText(f'Выделено: {len(self.selection)}')
            self.map_view.set_round_lines(
                map_marks(self._latest_round_events(), self._token_radius))
            self.map_view.set_focus_lines([])
            if self.selected is not None:
                self.map_info.setText(self._token_line(self.selected))
            else:
                self.map_info.setText('Токен не выбран.')
            self._refresh_initiative()
        finally:
            self._suspend_history = False
        self._current = snapshot
        self._sync_history_actions()

    def do_undo(self):
        if not self.history.can_undo():
            return
        label = self.history.undo_label()
        self._restore(self.history.undo())
        self.status.showMessage(f'Отменено: {label}')

    def do_redo(self):
        if not self.history.can_redo():
            return
        label = self.history.redo_label()
        self._restore(self.history.redo())
        self.status.showMessage(f'Повторено: {label}')

    # ================= настройка армий =================
    def _build_setup(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        self.cards_host = CardsHost(self)
        sa.setWidget(self.cards_host)
        lay.addWidget(sa, 1)
        row = QHBoxLayout()
        row.addStretch()
        create = QPushButton('⚔️  Создать армии')
        create.setProperty('variant', 'primary')
        create.setMinimumHeight(40)
        create.setMinimumWidth(220)
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.clicked.connect(self.create_armies)
        row.addWidget(create)
        row.addStretch()
        lay.addLayout(row)
        return page

    def _build_sides_dialog(self):
        dialog = QDialog(self)
        dialog.setObjectName('sides_dialog')
        dialog.setWindowTitle('Стороны')
        dialog.setModal(False)
        dialog.resize(960, 680)
        lay = QVBoxLayout(dialog)
        lay.setContentsMargins(10, 10, 10, 10)
        note = QLabel(
            'Шаблон отряда: имя, состав, тактика, число и портрет. '
            '«Создать армии» ставит всех на карту. Одно существо — '
            'правый щелчок по пустой клетке или «Бой → Добавить существо…».')
        note.setWordWrap(True)
        note.setProperty('role', 'muted')
        lay.addWidget(note)
        lay.addWidget(self._build_setup(), 1)
        dialog.finished.connect(self._sides_closed)
        dialog.hide()
        self.sides_dialog = dialog

    def show_sides(self):
        dialog = getattr(self, 'sides_dialog', None)
        if dialog is None:
            return
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if hasattr(self, 'armies_btn'):
            self.armies_btn.blockSignals(True)
            self.armies_btn.setChecked(True)
            self.armies_btn.blockSignals(False)
        self.cols = 0
        self.relayout_cards()

    def _sides_closed(self, _result=0):
        if not hasattr(self, 'armies_btn'):
            return
        self.armies_btn.blockSignals(True)
        self.armies_btn.setChecked(False)
        self.armies_btn.blockSignals(False)

    def add_side(self):
        self.add_card()
        self.show_sides()

    def relayout_cards(self):
        if not hasattr(self, 'plus_btn'):
            return
        w = self.cards_host.width()
        if w < 100:
            return
        cols = max(1, min(8, w // 340))
        if cols == self.cols and self.cards_host.grid.count():
            return
        self.cols = cols
        for i in range(8):
            self.cards_host.grid.setColumnStretch(i, 1 if i < cols else 0)
        for i, c in enumerate(self.cards):
            self.cards_host.grid.addWidget(c['frame'], i // cols, i % cols)
        if len(self.cards) < MAX_SIDES:
            self.plus_btn.show()
            self.cards_host.grid.addWidget(self.plus_btn, len(self.cards) // cols,
                                           len(self.cards) % cols,
                                           Qt.AlignmentFlag.AlignCenter)
        else:
            self.plus_btn.hide()

    def add_card(self, army_type=None, strategy='случайная', name=None, count=5):
        if len(self.cards) >= MAX_SIDES:
            return
        i = len(self.cards)
        types = types_available()
        army_type = army_type or types[0]
        pal = self.theme.palette()

        frame = PortraitCard(pal)
        frame.setMinimumWidth(300)
        outer = QGridLayout(frame)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QWidget()
        header.setObjectName('cardHeader')
        header.setStyleSheet('#cardHeader { background: transparent; }')
        header.setFixedHeight(frame.header_height())
        frame.header = header
        hl = QGridLayout(header)
        hl.setContentsMargins(14, 8, 10, 6)
        hl.setSpacing(4)
        title = QLineEdit(f'Сторона {chr(65 + i)}' if name is None else name)
        title.setProperty('role', 'title')
        cross = IconButton('cross', pal, size=26, outline=True)
        cross.setToolTip('Удалить отряд')
        hl.addWidget(cross, 0, 2, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        hl.addWidget(title, 1, 0, 1, 2,
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        hl.setRowStretch(0, 1)
        outer.addWidget(header, 0, 0)

        body = QWidget()
        body.setObjectName('cardBody')
        body.setStyleSheet('#cardBody { background: transparent; }')
        g = QGridLayout(body)
        g.setContentsMargins(14, 2, 12, 12)
        g.setVerticalSpacing(7)

        type_lbl = QLabel(army_type)
        type_lbl.setProperty('role', 'accent')
        type_lbl.setWordWrap(True)
        change = IconButton('swap', pal, size=28, outline=True)
        change.setToolTip('Изменить состав')
        g.addWidget(QLabel('Состав:'), 0, 0)
        g.addWidget(type_lbl, 0, 1)
        g.addWidget(change, 0, 2, Qt.AlignmentFlag.AlignRight)

        strat = QComboBox()
        strat.addItems(STRATS)
        strat.setCurrentText(strategy)
        g.addWidget(QLabel('Тактика:'), 1, 0)
        g.addWidget(strat, 1, 1, 1, 2)

        cnt = QSpinBox()
        cnt.setRange(0, 500)
        cnt.setValue(count)
        g.addWidget(QLabel('Количество:'), 2, 0)
        g.addWidget(cnt, 2, 1, 1, 2)

        prow = QHBoxLayout()
        prow.setSpacing(6)
        dice = IconButton('dice', pal, size=28, outline=True)
        dice.setToolTip('Другая картинка из галереи монстра')
        find = IconButton('image', pal, size=28, outline=True)
        find.setToolTip('Найти портрет на dnd.su по названию состава')
        pic_info = QLabel('портрет не загружен')
        pic_info.setProperty('role', 'muted')
        prow.addWidget(dice)
        prow.addWidget(find)
        prow.addWidget(pic_info, 1)
        g.addLayout(prow, 3, 0, 1, 3)
        g.setColumnStretch(1, 1)
        outer.addWidget(body, 1, 0)
        outer.setRowStretch(2, 1)

        card = {'frame': frame, 'name': title, 'type': army_type, 'type_lbl': type_lbl,
                'strat': strat, 'count': cnt, 'icons': [cross, change, dice, find],
                'pic_info': pic_info, 'dice': dice, 'alive': True, 'busy': False,
                'guard': qt_async.Guard()}
        cross.clicked.connect(lambda: self.remove_card(card))
        change.clicked.connect(lambda: self.change_composition(card))
        dice.clicked.connect(lambda: self._portrait_async(card))
        find.clicked.connect(lambda: self._portrait_async(card, search=True))
        title.editingFinished.connect(lambda c=card: self._on_side_name(c))
        strat.currentTextChanged.connect(lambda _text, c=card: self._on_side_strategy(c))
        cnt.editingFinished.connect(lambda c=card: self._on_side_count(c))
        self.cards.append(card)

        if not hasattr(self, 'plus_btn'):
            self.plus_btn = IconButton('plus', pal, size=48, outline=True, round_shape=True)
            self.plus_btn.setToolTip('Добавить сторону')
            self.plus_btn.clicked.connect(lambda: self.add_card())
            self._icon_buttons.append(self.plus_btn)
        for b in card['icons']:
            self._icon_buttons.append(b)
        self.cols = 0
        self.relayout_cards()
        self._show_cached_portrait(card)
        self._commit(f'добавление стороны {card["name"].text()}')

    def _on_side_name(self, card):
        if not card.get('alive', True):
            return
        self._commit(f'имя стороны {card["name"].text()}')

    def _on_side_strategy(self, card):
        if not card.get('alive', True):
            return
        self._commit(f'тактика: {card["name"].text()}')

    def _on_side_count(self, card):
        if not card.get('alive', True):
            return
        self._commit(f'число существ: {card["name"].text()}')

    # ---------- портреты ----------
    def _show_cached_portrait(self, card):
        path = portraits.local_path(card['type'])
        total = len(portraits.urls_for(card['type']))
        if path:
            pix = QPixmap(path)
            if not pix.isNull():
                card['frame'].set_portrait(pix)
                idx = portraits.pick(card['type'], self._current_index(card['type']))
                card['pic_info'].setText(f'портрет {(idx or 0) + 1} / {total}')
                card['dice'].setEnabled(total > 1)
                return
        card['frame'].set_portrait(None)
        card['pic_info'].setText(f'галерея: {total}' if total else 'портрет не загружен')
        card['dice'].setEnabled(total > 1)

    @staticmethod
    def _current_index(type_name):
        import json as _json
        try:
            with open(portraits.INDEX_FILE, 'r', encoding='utf-8') as f:
                return (_json.load(f).get(type_name) or {}).get('index')
        except Exception:
            return None

    def _portrait_async(self, card, search=False, index=None, tries=0):
        if not card.get('alive') or card.get('busy'):
            return
        card['busy'] = True
        card['pic_info'].setText('загрузка портрета…')
        fn = portraits.find_and_cache if search else portraits.ensure_local
        args = (card['type'],) if search else (card['type'], index)
        qt_async.submit(fn, args,
                        on_ok=lambda res: self._portrait_done(card, res, tries),
                        on_fail=lambda msg: self._portrait_fail(card, msg),
                        guard=card.get('guard'))

    def _portrait_done(self, card, res, tries=0):
        if not card.get('alive'):
            return
        card['busy'] = False
        if not res:
            card['pic_info'].setText('галерея не найдена')
            card['frame'].set_portrait(None)
            return
        pix = QPixmap(res['path'])
        if pix.isNull():
            card['pic_info'].setText('файл не читается')
            return
        # качество: превью-мелочь не растягиваем — берём следующий кандидат
        if min(pix.width(), pix.height()) < 260 and res['total'] > 1 and tries < res['total'] - 1:
            card['pic_info'].setText('ищем вариант крупнее…')
            self._portrait_async(card, index=(res['index'] + 1) % res['total'], tries=tries + 1)
            return
        card['frame'].set_portrait(pix)
        card['pic_info'].setText(f"портрет {res['index'] + 1} / {res['total']}")
        card['dice'].setEnabled(res['total'] > 1)
        self.status.showMessage(f"Портрет загружен: {card['type']}")

    def _portrait_fail(self, card, msg):
        if not card.get('alive'):
            return
        card['busy'] = False
        card['pic_info'].setText('не удалось загрузить')
        self.status.showMessage(f'Портрет: {msg}')

    def remove_card(self, card):
        if len(self.cards) <= 1:
            QMessageBox.information(self, 'Отряд', 'Должна остаться хотя бы одна сторона.')
            return
        side_name = card['name'].text()
        if QMessageBox.question(self, 'Удалить отряд?', f'Удалить «{side_name}»?',
                                QMessageBox.StandardButton.Yes |
                                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        card['alive'] = False
        if card.get('guard') is not None:
            card['guard'].drop()
        self.cards.remove(card)
        for b in card['icons']:
            if b in self._icon_buttons:
                self._icon_buttons.remove(b)
        card['frame'].setParent(None)
        card['frame'].deleteLater()
        self.cols = 0
        self.relayout_cards()
        self._commit(f'удаление стороны {side_name}')

    def change_composition(self, card):
        d = SideCreatorDialog(self, types_available(), mode='edit', current_type=card['type'])
        d.ready.connect(lambda res: self._apply_composition(card, res))
        d.exec()

    def _apply_composition(self, card, res):
        card['type'] = res['army_type']
        card['type_lbl'].setText(res['army_type'])
        card['strat'].blockSignals(True)
        card['strat'].setCurrentText(res['strategy'])
        card['strat'].blockSignals(False)
        self.status.showMessage(f'Состав обновлён: {res["army_type"]}')
        self._show_cached_portrait(card)
        self._commit(f'состав: {res["army_type"]}')
        if portraits.local_path(card['type']) is None:
            self._portrait_async(card, search=not portraits.urls_for(card['type']))

    def create_armies(self):
        self.pause_auto()
        try:
            self.sides, self.side_names = [], []
            for i, c in enumerate(self.cards):
                name = c['name'].text().strip() or f'Сторона {chr(65 + i)}'
                self.side_names.append(name)
                side = []
                for j in range(c['count'].value()):
                    e = EnemyFactory.create_enemy(c['type'], f'{name}_{j + 1}', i)
                    e.strategy = make_strategy(c['strat'].currentText())
                    side.append(e)
                self.sides.append(side)
            n = len(self.sides)
            max_side = max((len(s) for s in self.sides), default=0)
            map_w = max(24, 4 * n)
            zone_cols = max(1, map_w // n)
            map_h = max(16, (max_side + zone_cols - 1) // zone_cols + 2)
            old_map = self.battle_map
            self.battle_map = BattleMap(width=map_w, height=map_h)
            if old_map is not None:
                self.battle_map.copy_terrain_from(old_map)
            self.ignore_sides = {}
            self.selected = None
            self.selection = []
            self.round_no = 0
            self.battle_events = []
            self.battle_map.formation_placement(self.sides)
            self.rebuild_battle_lists()
            self.refresh_alliances()
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
            self.map_info.setText('Токен не выбран.')
            self.map_view.set_round_lines([])
            self.map_view.set_area_cells([])
            self.map_view.set_preview_cells([])
            self.map_view.set_focus_areas([])
            self.log_panel.clear()
            self.log_panel.set_roster(self.sides, self.side_names)
            self._refresh_initiative()
            total = sum(len(s) for s in self.sides)
            self.battle_events.extend(self.log_panel.add_note(
                f'Армии созданы: сторон {n}, существ {total}.'))
            self.status.showMessage(f'Армии созданы: {n} сторон, {total} существ.')
            self._commit('создание армий')
            self.select_tab(1)
        except Exception as e:
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, 'Ошибка', f'Ошибка при создании армий: {e}')

    # ================= битва =================
    def _outline(self, text, slot, name=None):
        button = QPushButton(text)
        button.setProperty('variant', 'outline')
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(slot)
        if name:
            button.setObjectName(name)
        return button

    def _build_roster(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)
        cap = QLabel('Порядок хода')
        cap.setProperty('role', 'title')
        lay.addWidget(cap)
        self.initiative_list = QListWidget()
        self.initiative_list.setObjectName('initiative_list')
        self.initiative_list.setMaximumHeight(168)
        self.initiative_list.itemDoubleClicked.connect(self._focus_initiative_item)
        self.initiative_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.initiative_list.customContextMenuRequested.connect(self._initiative_menu)
        lay.addWidget(self.initiative_list)
        self.battle_scroll = QScrollArea()
        self.battle_scroll.setWidgetResizable(True)
        self.battle_host = QWidget()
        self.battle_lay = QVBoxLayout(self.battle_host)
        self.battle_lay.setContentsMargins(0, 0, 0, 0)
        self.battle_scroll.setWidget(self.battle_host)
        lay.addWidget(self.battle_scroll, 1)
        lay.addWidget(self._outline('Добавить существо…', self.prompt_add_creature,
                                    'add_creature'))
        lay.addWidget(self._outline('Массовое редактирование', self.mass_edit))
        return page

    def _build_log_tab(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        self.log_panel = CombatLogPanel()
        self.log_panel.entry_activated.connect(self.on_log_entry)
        lay.addWidget(self.log_panel, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.copy_btn = self._outline('📋 Копировать лог', self.copy_log, 'copy_log')
        row.addWidget(self.copy_btn)
        row.addWidget(self._outline('Экспорт журнала', self.export_log))
        row.addWidget(self._outline('Очистить результаты', self.clear_log))
        lay.addLayout(row)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        row2.addWidget(self._outline('Показать статус', self.show_status))
        row2.addWidget(self._outline('Анализ сражения', self.open_analysis))
        lay.addLayout(row2)
        self.batch_btn = QPushButton('Пакетная симуляция…')
        self.batch_btn.setObjectName('batch_sim')
        self.batch_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.batch_btn.clicked.connect(self.open_batch)
        lay.addWidget(self.batch_btn)
        return page

    def _build_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setObjectName('battle_settings')
        dialog.setWindowTitle('Настройки боя')
        dialog.setModal(False)
        dialog.resize(480, 680)
        outer = QVBoxLayout(dialog)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(8)
        note = QLabel('Редкие правила и вид карты. Частые команды — на панели слева и в меню.')
        note.setProperty('role', 'muted')
        note.setWordWrap(True)
        outer.addWidget(note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(4, 4, 8, 4)
        lay.setSpacing(8)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        rules = Section('Правила боя')
        self._sec_rules = rules
        self._build_rules_section(rules.body_lay)
        lay.addWidget(rules)

        display = Section('Отображение карты')
        self._sec_display = display
        self._build_display_section(display.body_lay)
        lay.addWidget(display)

        background = Section('Фон карты')
        self._sec_bg = background
        self._build_background_section(background.body_lay)
        lay.addWidget(background)

        allies = Section('Альянсы')
        self._sec_alliances = allies
        allies.body_lay.addWidget(self._build_alliances())
        lay.addWidget(allies)
        lay.addStretch()
        rules.arrow.setChecked(True)
        self.settings_dialog = dialog

    def _build_rules_section(self, lay):
        crit_row = QHBoxLayout()
        crit_row.addWidget(QLabel('Крит:'))
        self.crit_mode = QComboBox()
        self.crit_mode.setObjectName('crit_mode')
        self.crit_mode.addItem('Удваивать весь урон', 'double_all')
        self.crit_mode.addItem('Удваивать только кости', 'dice_only')
        self.crit_mode.setCurrentIndex(0)
        crit_row.addWidget(self.crit_mode, 1)
        lay.addLayout(crit_row)

        self.auto_move = QCheckBox('Автоперемещение в бою')
        self.auto_move.setObjectName('auto_move')
        self.auto_move.setChecked(True)
        self.auto_move.setToolTip('Бойцы сами подходят на дистанцию удара')
        lay.addWidget(self.auto_move)

        self.hide_hp = QCheckBox('Скрывать хиты в списках')
        self.hide_hp.setObjectName('hide_hp')
        self.hide_hp.setToolTip(
            'В списке участников и в строке карты вместо чисел будет «хиты скрыты». '
            'Журнал по-прежнему хранит точные хиты.')
        self.hide_hp.toggled.connect(self._on_hide_hp)
        lay.addWidget(self.hide_hp)

        self.manual_toggle = QCheckBox('Ручное управление')
        self.manual_toggle.setObjectName('manual_toggle')
        self.manual_toggle.setToolTip(
            'На ходу выбранного существа или его стороны раунд останавливается: '
            'цель и область выбираете вы')
        self.manual_scope = QComboBox()
        self.manual_scope.setObjectName('manual_scope')
        self.manual_scope.addItems(['Выбранное существо', 'Сторона выбранного'])
        lay.addWidget(self.manual_toggle)
        lay.addWidget(self.manual_scope)

        self.manual_map_toggle = QCheckBox('Ручное управление', self)
        self.manual_map_toggle.setObjectName('manual_map_toggle')
        self.manual_map_toggle.hide()
        self.manual_map_scope = QComboBox(self)
        self.manual_map_scope.setObjectName('manual_map_scope')
        self.manual_map_scope.addItems(['Выбранное существо', 'Сторона выбранного'])
        self.manual_map_scope.hide()
        self.manual_toggle.toggled.connect(self._sync_manual_toggle)
        self.manual_scope.currentIndexChanged.connect(self._sync_manual_scope)
        self.manual_map_toggle.toggled.connect(self._sync_manual_toggle_from_map)
        self.manual_map_scope.currentIndexChanged.connect(self._sync_manual_scope_from_map)

    def _on_hide_hp(self, _checked):
        self.refresh_all_labels()
        if self.selected is not None and self._manual_loop is None:
            self.on_token(self.selected)

    def _build_dock(self):
        from qt_bestiary import BestiaryDialog
        self.bestiary = BestiaryDialog(self, embedded=True)
        self.bestiary.imported.connect(self._on_bestiary_import)
        self.side_tabs = QTabWidget()
        self.side_tabs.setObjectName('side_tabs')
        self.side_tabs.setTabPosition(QTabWidget.TabPosition.East)
        self.side_tabs.setIconSize(QSize(18, 18))
        self.side_tabs.addTab(self.roster_page, 'Участники')
        self.side_tabs.addTab(self.log_page, 'Журнал')
        self.side_tabs.addTab(self.bestiary, 'Бестиарий')
        self.side_tabs.setTabToolTip(0, 'Инициатива и участники')
        self.side_tabs.setTabToolTip(1, 'Журнал боя')
        self.side_tabs.setTabToolTip(2, 'Бестиарий dnd.su')
        self._refresh_tab_icons()
        dock = QDockWidget('Панель боя', self)
        dock.setObjectName('side_dock')
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        dock.setWidget(self.side_tabs)
        self.side_dock = dock
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.resizeDocks([dock], [420], Qt.Orientation.Horizontal)

    def rebuild_battle_lists(self):
        sig = (
            tuple(tuple(id(enemy) for enemy in side) for side in self.sides),
            tuple(self.side_names),
        )
        if sig == self._roster_sig and self.enemy_labels:
            self.refresh_all_labels()
            self._sync_checks()
            return
        self.battle_host.setUpdatesEnabled(False)
        try:
            self._rebuild_battle_lists_full()
            self._roster_sig = sig
        finally:
            self.battle_host.setUpdatesEnabled(True)
        self._sync_checks()

    def _rebuild_battle_lists_full(self):
        clear_layout(self.battle_lay)
        self.enemy_labels, self.side_checks, self.side_all_checks = {}, [], []
        if not any(self.sides):
            hint = QLabel('На карте пока никого. Правый щелчок по клетке, '
                          '«Добавить существо…» или «Создать армии».')
            hint.setProperty('role', 'muted')
            self.battle_lay.addWidget(hint)
            self.battle_lay.addStretch()
            return
        cols = 1
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (side, name) in enumerate(zip(self.sides, self.side_names)):
            box = QGroupBox(name)
            bl = QVBoxLayout(box)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setMinimumHeight(min(220, 28 * (len(side) + 2)))
            host = QWidget()
            hl = QVBoxLayout(host)
            hl.setContentsMargins(4, 4, 4, 4)
            all_cb = QCheckBox('Выделить сторону')
            all_cb.setObjectName(f'select_side_{i}')
            all_cb.setTristate(True)
            hl.addWidget(all_cb)
            checks = []
            for e in side:
                e.attach(self.updater)
                r = QHBoxLayout()
                cb = QCheckBox()
                lab = QLabel(self._enemy_text(e))
                lab.setToolTip(self._enemy_tip(e))
                lab.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                lab.customContextMenuRequested.connect(
                    lambda pos, en=e, widget=lab: self.open_token_menu(
                        en, widget.mapToGlobal(pos)))
                lab.mouseDoubleClickEvent = lambda ev, en=e: self.edit_one(en)
                lab.mousePressEvent = lambda ev, en=e, widget=lab: self._roster_press(ev, en, widget)
                cb.toggled.connect(lambda on, en=e: self._on_roster_check(en, on))
                r.addWidget(cb)
                r.addWidget(lab, 1)
                hl.addLayout(r)
                checks.append(cb)
                self.enemy_labels[e] = lab
            hl.addStretch()
            sa.setWidget(host)
            bl.addWidget(sa)
            all_cb.clicked.connect(lambda checked, idx=i: self._on_side_toggle(idx, checked))
            self.side_checks.append(checks)
            self.side_all_checks.append(all_cb)
            grid.addWidget(box, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        self.battle_lay.addLayout(grid)

    def _enemy_text(self, e):
        from conditions import condition_marks
        status = '🟢' if e.alive else '🔴'
        atk = ', '.join(f'{a.name}{"✦" if getattr(a, "magical", False) else ""}'
                        f'+{a.attack_bonus}' for a in e.attacks)
        marks = condition_marks(e)
        suffix = f' · {marks}' if marks else ''
        hidden = getattr(self, 'hide_hp', None) is not None and self.hide_hp.isChecked()
        hp = 'хиты скрыты' if hidden else f'{e.hp}/{e.max_hp} HP'
        return f'{status} {e.name}: {hp} [{atk}]{suffix}'

    @staticmethod
    def _enemy_tip(e):
        from conditions import condition_tooltip
        return condition_tooltip(e)

    def _token_line(self, enemy):
        from conditions import condition_marks, effective_speed
        pos = None if self.battle_map is None else self.battle_map.get_pos(enemy)
        speed = effective_speed(enemy)
        left = speed - getattr(enemy, 'moved_ft', 0)
        marks = condition_marks(enemy)
        tail = f', {marks}' if marks else ''
        hidden = getattr(self, 'hide_hp', None) is not None and self.hide_hp.isChecked()
        hp = 'хиты скрыты, ' if hidden else f'HP {enemy.hp}/{enemy.max_hp}, '
        return (f'{enemy.name}: {hp}AC {enemy.ac}, клетка {pos}, '
                f'скорость {speed} фт, остаток {left} фт{tail}')

    def _refresh_initiative(self):
        listing = getattr(self, 'initiative_list', None)
        if listing is None:
            return
        listing.clear()
        event = next((item for item in reversed(self.battle_events)
                      if getattr(item, 'kind', None) == 'initiative'), None)
        if event is None or not event.rolls:
            empty = QListWidgetItem('Порядок хода появится после раунда')
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            listing.addItem(empty)
            return
        colors = SIDE_PALETTES.get('classic', [])
        for roll in event.rolls:
            enemy = self._find_enemy(roll.actor_id)
            item = QListWidgetItem(f'{roll.total:>2}   {roll.name}')
            item.setData(Qt.ItemDataRole.UserRole, enemy)
            side = roll.side if roll.side is not None else 0
            if colors:
                item.setForeground(QColor(colors[int(side) % len(colors)]))
            listing.addItem(item)
        self._mark_initiative_selection()

    def _focus_initiative_item(self, item):
        enemy = item.data(Qt.ItemDataRole.UserRole)
        if enemy is None or self._manual_loop is not None:
            return
        self.on_token(enemy)

    def _mark_initiative_selection(self):
        listing = getattr(self, 'initiative_list', None)
        if listing is None:
            return
        for row in range(listing.count()):
            item = listing.item(row)
            if item.data(Qt.ItemDataRole.UserRole) is self.selected:
                listing.setCurrentItem(item)
                return

    def _initiative_menu(self, pos):
        item = self.initiative_list.itemAt(pos)
        if item is None:
            return
        enemy = item.data(Qt.ItemDataRole.UserRole)
        if enemy is None:
            return
        self.open_token_menu(enemy, self.initiative_list.mapToGlobal(pos))

    def open_token_menu(self, enemy, global_pos):
        if enemy is None:
            return
        if enemy not in self.selection:
            self.set_selection([enemy])
        if len(self.selection) > 1 and enemy in self.selection:
            menu = self.build_group_menu(self.selection)
        else:
            menu = self.build_token_menu(enemy)
        menu.exec(global_pos)

    def build_token_menu(self, enemy):
        """Контекстное меню токена и строки участника. Не блокирует само по себе."""
        from conditions import CATALOG, active_conditions, condition_name
        menu = QMenu(self)
        menu.setObjectName('token_menu')
        sheet = menu.addAction('Карточка существа', lambda: self.edit_one(enemy))
        sheet.setObjectName('token_sheet')
        menu.addSeparator()
        duplicate = menu.addAction('Дублировать', lambda: self.duplicate_enemy(enemy))
        duplicate.setObjectName('token_duplicate')
        delete = menu.addAction('Удалить…', lambda: self.delete_enemy(enemy))
        delete.setObjectName('token_delete')
        sides = menu.addMenu('Сменить сторону')
        sides.setObjectName('token_side')
        for index, name in enumerate(self.side_names):
            action = sides.addAction(
                name, lambda _checked=False, idx=index, who=enemy: self.change_enemy_side(
                    who, idx))
            action.setCheckable(True)
            action.setChecked(index == getattr(enemy, 'side', None))
        if self.side_names:
            sides.addSeparator()
        sides.addAction('Новая сторона…', lambda who=enemy: self.change_enemy_side(who, -1))
        move = menu.addAction('Переместить', lambda: self.begin_relocate(enemy))
        move.setObjectName('token_move')
        menu.addSeparator()
        add = menu.addMenu('Наложить состояние')
        add.setObjectName('token_conditions')
        for condition_id, label, _short, _color, hidden in CATALOG:
            if hidden or condition_id == 'exhaustion':
                continue
            add.addAction(label, lambda _checked=False, cid=condition_id: self._impose(
                enemy, cid))
        levels = menu.addMenu('Истощение')
        for level in range(0, 7):
            title = 'снять' if level == 0 else f'уровень {level}'
            levels.addAction(title, lambda _checked=False, value=level: self._set_exhaustion(
                enemy, value))
        remove = menu.addMenu('Снять состояние')
        current = [item for item in active_conditions(enemy) if isinstance(item, dict)]
        if not current:
            empty = remove.addAction('нет состояний')
            empty.setEnabled(False)
        for item in current:
            title = condition_name(item.get('id'))
            if item.get('id') == 'exhaustion':
                title = f'{title} {item.get("level")}'
            remove.addAction(title, lambda _checked=False, cond=item: self._lift(enemy, cond))
        return menu

    def build_group_menu(self, enemies):
        """Действия по выделенной группе. Каждый пункт — один шаг отмены."""
        from conditions import CATALOG, active_conditions, condition_name
        enemies = [enemy for enemy in enemies if enemy is not None]
        menu = QMenu(self)
        menu.setObjectName('group_menu')
        title = menu.addAction(f'Выделено: {len(enemies)}')
        title.setEnabled(False)
        sheet = menu.addAction('Карточка выделенных', lambda: self.open_creature_sheet(enemies))
        sheet.setObjectName('group_sheet')
        menu.addSeparator()
        duplicate = menu.addAction('Дублировать', lambda: self.duplicate_group(enemies))
        duplicate.setObjectName('group_duplicate')
        delete = menu.addAction('Удалить…', lambda: self.delete_group(enemies))
        delete.setObjectName('group_delete')
        sides = menu.addMenu('Сменить сторону')
        sides.setObjectName('group_side')
        for index, name in enumerate(self.side_names):
            sides.addAction(
                name, lambda _checked=False, idx=index, who=list(enemies): self.change_group_side(
                    who, idx))
        sides.addAction('Новая сторона…', lambda who=list(enemies): self.change_group_side(who, -1))
        move = menu.addAction('Переместить', lambda: self.begin_relocate_group(enemies))
        move.setObjectName('group_move')
        menu.addSeparator()
        harm = menu.addAction('Нанести урон…', lambda: self.damage_group(enemies))
        harm.setObjectName('group_damage')
        heal = menu.addAction('Лечить…', lambda: self.heal_group(enemies))
        heal.setObjectName('group_heal')
        menu.addSeparator()
        add = menu.addMenu('Наложить состояние')
        add.setObjectName('group_conditions')
        for condition_id, label, _short, _color, hidden in CATALOG:
            if hidden or condition_id == 'exhaustion':
                continue
            add.addAction(
                label, lambda _checked=False, cid=condition_id, who=list(enemies):
                self._impose_group(who, cid))
        levels = menu.addMenu('Истощение')
        for level in range(0, 7):
            title = 'снять' if level == 0 else f'уровень {level}'
            levels.addAction(
                title, lambda _checked=False, value=level, who=list(enemies):
                self._exhaust_group(who, value))
        remove = menu.addMenu('Снять состояние')
        remove.setObjectName('group_clear_conditions')
        seen = []
        for enemy in enemies:
            for item in active_conditions(enemy):
                if isinstance(item, dict) and item.get('id') not in seen:
                    seen.append(item.get('id'))
        if not seen:
            empty = remove.addAction('нет состояний')
            empty.setEnabled(False)
        for condition_id in seen:
            remove.addAction(
                condition_name(condition_id),
                lambda _checked=False, cid=condition_id, who=list(enemies):
                self._lift_group(who, cid))
        return menu

    def open_cell_menu(self, x, y, global_pos):
        if self._manual_loop is not None:
            return
        menu = self.build_cell_menu(x, y)
        menu.exec(global_pos)

    def build_cell_menu(self, x, y):
        menu = QMenu(self)
        menu.setObjectName('cell_menu')
        action = menu.addAction(
            'Добавить существо сюда…',
            lambda: self.prompt_add_creature(x, y))
        action.setObjectName('cell_add')
        return menu

    def open_condition_menu(self, enemy, global_pos):
        """Совместимость: полный контекст токена, не только состояния."""
        self.open_token_menu(enemy, global_pos)

    def _impose(self, enemy, condition_id):
        from conditions import apply_condition, permanent_duration
        if apply_condition(enemy, condition_id, duration=permanent_duration(),
                           note='вручную') is None:
            self.status.showMessage(
                f'{enemy.name} не получает состояние (иммунитет или уже нельзя)')
            return
        self._after_condition_edit(enemy, f'состояние: {enemy.name}')

    def _set_exhaustion(self, enemy, level):
        from conditions import set_exhaustion
        set_exhaustion(enemy, level)
        self._after_condition_edit(enemy, f'истощение: {enemy.name}')

    def _lift(self, enemy, cond):
        from conditions import remove_condition
        remove_condition(enemy, cond=cond, reason='снято вручную')
        self._after_condition_edit(enemy, f'снято состояние: {enemy.name}')

    def _after_condition_edit(self, enemy, label):
        self.refresh_all_labels()
        if self.battle_map is not None:
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self.on_token(enemy)
        self._commit(label)

    def refresh_dirty(self):
        for e in list(self.dirty):
            lab = self.enemy_labels.get(e)
            if lab is not None:
                lab.setText(self._enemy_text(e))
                lab.setToolTip(self._enemy_tip(e))
        self.dirty.clear()

    def refresh_all_labels(self):
        for e, lab in self.enemy_labels.items():
            lab.setText(self._enemy_text(e))
            lab.setToolTip(self._enemy_tip(e))
        self.dirty.clear()

    def run_round(self):
        if self._round_busy:
            return
        self._round_busy = True
        self._manual_subjects = self._manual_subject_ids()
        self.round_btn.setEnabled(False)
        if hasattr(self, 'act_round'):
            self.act_round.setEnabled(False)
        try:
            result = battle_round.run_round(
                self.sides, self.side_names, self.ignore_sides, self.battle_map,
                self.engine, auto_move=self.auto_move.isChecked(),
                crit_mode=self.crit_mode.currentData(), round_no=self.round_no + 1,
                controller=self._manual_controller)
        finally:
            self.round_btn.setEnabled(True)
            if hasattr(self, 'act_round'):
                self.act_round.setEnabled(True)
            self._manual_subjects = set()
            self._close_manual_ui()
            self._round_busy = False
        outcome, text = result
        if outcome == 'empty':
            self.pause_auto()
            QMessageBox.warning(self, 'Ошибка', text)
            return
        self.round_no += 1
        self.battle_events.extend(result.events)
        self.suspend = True
        self.log_panel.append_round(result.events)
        self.suspend = False
        self.refresh_all_labels()
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self.map_view.set_round_lines(map_marks(result.events, self._token_radius))
        self.map_view.set_preview_cells([])
        self.map_view.set_focus_areas([])
        self.map_view.set_area_cells(self._area_cells(result.events))
        alive = sum(1 for s in self.sides for e in s if e.alive)
        attacks = sum(1 for event in result.events if event.kind == 'attack')
        self._refresh_initiative()
        self.status.showMessage(
            f'Раунд {self.round_no}: живых {alive}, атак {attacks}' +
            ('  ·  бой завершён' if outcome == 'over' else '') +
            '  ·  линии атак на карте')
        self._commit(f'раунд {self.round_no}')
        if outcome == 'over':
            self.pause_auto()

    def _sync_manual_toggle(self, checked):
        if getattr(self, 'manual_map_toggle', None) is None:
            return
        self.manual_map_toggle.blockSignals(True)
        self.manual_map_toggle.setChecked(bool(checked))
        self.manual_map_toggle.blockSignals(False)
        action = getattr(self, 'act_manual', None)
        if action is not None and action.isChecked() != bool(checked):
            action.blockSignals(True)
            action.setChecked(bool(checked))
            action.blockSignals(False)

    def _sync_manual_toggle_from_map(self, checked):
        self.manual_toggle.blockSignals(True)
        self.manual_toggle.setChecked(bool(checked))
        self.manual_toggle.blockSignals(False)

    def _sync_manual_scope(self, index):
        if getattr(self, 'manual_map_scope', None) is None:
            return
        self.manual_map_scope.blockSignals(True)
        self.manual_map_scope.setCurrentIndex(index)
        self.manual_map_scope.blockSignals(False)
        self._sync_scope_actions(index)

    def _sync_manual_scope_from_map(self, index):
        self.manual_scope.blockSignals(True)
        self.manual_scope.setCurrentIndex(index)
        self.manual_scope.blockSignals(False)
        self._sync_scope_actions(index)

    def _sync_scope_actions(self, index):
        one = getattr(self, 'act_scope_one', None)
        side = getattr(self, 'act_scope_side', None)
        if one is None or side is None:
            return
        one.blockSignals(True)
        side.blockSignals(True)
        one.setChecked(index == 0)
        side.setChecked(index == 1)
        one.blockSignals(False)
        side.blockSignals(False)

    def _manual_subject_ids(self):
        if not self.manual_toggle.isChecked() or self.selected is None:
            return set()
        if self.manual_scope.currentIndex() == 1:
            side = getattr(self.selected, 'side', None)
            return {id(enemy) for group in self.sides for enemy in group
                    if getattr(enemy, 'side', None) == side and enemy.alive}
        if getattr(self.selected, 'alive', False):
            return {id(self.selected)}
        return set()

    def _manual_controller(self, attacker, side_idx):
        del side_idx
        if id(attacker) not in self._manual_subjects:
            return None
        return self._ask_manual(attacker)

    def _close_manual_ui(self):
        loop = self._manual_loop
        self._manual_loop = None
        if loop is not None and loop.isRunning():
            loop.quit()
        if getattr(self, 'manual_bar', None) is not None:
            self.manual_bar.hide()
        if getattr(self, 'map_view', None) is not None:
            self.map_view.set_aiming(False)
            self.map_view.set_cover_hover(False)
            self.map_view.set_cover_overlay(None, None)
            if getattr(self, 'terrain_btn', None) is not None and self.terrain_btn.isChecked():
                self.map_view.set_terrain_mode(True)

    def _ask_manual(self, attacker):
        self._manual_actor = attacker
        self._manual_order = battle_round.ManualAction('auto')
        self._manual_target = None
        self._manual_placement = None
        self._manual_include = None
        self._aim_locked = False
        self._fill_manual_actions(attacker)
        self.select_tab(3)
        self.selected = attacker
        self.map_view.rebuild(self.battle_map, self.sides, attacker)
        pos = self.battle_map.get_pos(attacker) if self.battle_map is not None else None
        self.manual_title.setText(f'Ход: {attacker.name}' + (f' · клетка {pos}' if pos else ''))
        self.map_info.setText(
            f'Ручной ход {attacker.name}. Клетка задаёт направление или точку области, '
            'токен — цель атаки.')
        self.manual_bar.show()
        self._apply_manual_action()
        self.map_view.set_terrain_mode(False)
        self.map_view.set_aiming(True)
        loop = QEventLoop()
        self._manual_loop = loop
        loop.exec()
        order = self._manual_order
        self._manual_actor = None
        return order

    def _fill_manual_actions(self, attacker):
        from effects import (_area_phrase, opening_effects, recharge_ready,
                             replacing_effect)
        self.manual_action.blockSignals(True)
        self.manual_action.clear()
        self._manual_choices = []
        for attack in getattr(attacker, 'attacks', None) or []:
            self.manual_action.addItem(f'Атака: {attack.name}')
            self._manual_choices.append(('attack', attack, None))
        breath = replacing_effect(attacker)
        effects = []
        if breath:
            effects.append(breath)
        for effect in opening_effects(attacker):
            if effect is breath:
                continue
            if effect.get('recharge') and not recharge_ready(attacker, effect.get('name')):
                continue
            effects.append(effect)
        for effect in effects:
            phrase = _area_phrase(effect, None, None)
            self.manual_action.addItem(f'Область: {effect.get("name")} ({phrase})')
            self._manual_choices.append(('effect', None, effect))
        if not self._manual_choices:
            self.manual_action.addItem('Нет действий')
            self._manual_choices.append(('skip', None, None))
        prefer = next((index for index, item in enumerate(self._manual_choices)
                       if item[0] == 'effect'), 0)
        self.manual_action.setCurrentIndex(prefer)
        self.manual_action.blockSignals(False)

    def _apply_manual_action(self):
        if not self._manual_choices or getattr(self, '_manual_actor', None) is None:
            return
        kind, attack, effect = self._manual_choices[self.manual_action.currentIndex()]
        self._manual_kind = kind
        self._manual_attack = attack
        self._manual_effect = effect
        self._manual_target = None
        self._manual_placement = None
        self._manual_include = None
        self._aim_locked = False
        self.map_view.set_preview_cells([])
        self.map_view.set_cover_hover(False)
        self.map_view.set_cover_overlay(None, None)
        if kind == 'effect' and effect is not None:
            from effects import best_placement
            side = getattr(self._manual_actor, 'side', 0)
            placement = best_placement(
                self._manual_actor, effect, self.sides,
                self.ignore_sides.get(side, set()), self.battle_map)
            self._manual_placement = placement
            if placement is not None:
                self.map_view.set_preview_cells(placement.cells)
            self.manual_hint.setText(
                'Клик по клетке или токену задаёт направление или точку. '
                'Повторный клик по существу в области «на выбор» включает и исключает его.')
            self.manual_go.setEnabled(True)
        elif kind == 'attack':
            self.manual_hint.setText(
                'Кликните по токену — это цель атаки. Полное укрытие выбрать нельзя.')
            self.manual_go.setEnabled(False)
            self.map_view.set_cover_hover(True)
        else:
            self.manual_hint.setText('У существа нет действий. Ход можно пропустить.')
            self.manual_go.setEnabled(False)
        self._refresh_manual_hit()

    def _refresh_manual_hit(self):
        attacker = getattr(self, '_manual_actor', None)
        if attacker is None:
            self.manual_hit.setText('')
            return
        if self._manual_kind == 'attack':
            target = self._manual_target
            self.manual_hit.setText(
                f'Цель: {target.name}' if target is not None else 'Цель: не выбрана')
            return
        placement = self._manual_placement
        effect = self._manual_effect
        if placement is None or effect is None:
            self.manual_hit.setText('В этом направлении никого нет.')
            return
        creatures = list(placement.creatures)
        if effect.get('choice'):
            if self._manual_include is None:
                self._manual_include = [
                    creature for creature in creatures
                    if getattr(creature, 'side', None) != getattr(attacker, 'side', None)]
            names = ', '.join(creature.name for creature in self._manual_include) or 'никого'
            self.manual_hit.setText(f'На выбор: {names}')
            return
        names = ', '.join(creature.name for creature in creatures) or 'никого'
        allies = [creature.name for creature in creatures
                  if getattr(creature, 'side', None) == getattr(attacker, 'side', None)]
        tail = f' · свои: {", ".join(allies)}' if allies else ''
        self.manual_hit.setText(f'Задеты: {names}{tail}')

    def _manual_aim(self, point):
        from effects import aim_at
        attacker = self._manual_actor
        effect = self._manual_effect
        if attacker is None or effect is None or self.battle_map is None:
            return
        side = getattr(attacker, 'side', 0)
        placement = aim_at(
            attacker, effect, self.battle_map, point, self.sides,
            self.ignore_sides.get(side, set()))
        self._manual_placement = placement
        self.map_view.set_preview_cells(placement.cells if placement is not None else [])
        self._manual_include = None
        self._refresh_manual_hit()

    def _manual_cover(self, enemy):
        battle_map = self.battle_map
        attacker = getattr(self, '_manual_actor', None)
        if (battle_map is None or attacker is None or not battle_map.has_terrain()
                or battle_map.get_pos(attacker) is None or battle_map.get_pos(enemy) is None):
            return None
        return battle_map.combat_cover(attacker, enemy)

    def on_hover_target(self, enemy):
        if self._manual_loop is None or getattr(self, '_manual_kind', None) != 'attack':
            return
        attacker = getattr(self, '_manual_actor', None)
        if enemy is None or enemy is attacker or not getattr(enemy, 'alive', False):
            if self._manual_target is None:
                self.map_view.set_cover_overlay(None, None)
            return
        cover = self._manual_cover(enemy)
        if not cover:
            return
        from terrain import COVER_LABEL
        self.map_view.set_cover_overlay(enemy, cover)
        self.status.showMessage(f'{enemy.name}: {COVER_LABEL.get(cover, cover)}')

    def on_aim(self, x, y):
        if self._manual_loop is None or self._aim_locked or self._manual_kind != 'effect':
            return
        self._manual_aim((x, y))

    def _manual_click_cell(self, x, y):
        if self._manual_kind != 'effect':
            return
        self._aim_locked = True
        self._manual_aim((x, y))

    def _manual_click_token(self, enemy):
        if enemy is None or enemy is self._manual_actor or not getattr(enemy, 'alive', False):
            return
        if self._manual_kind == 'attack':
            cover = self._manual_cover(enemy)
            if cover == 'total':
                self._manual_target = None
                self.manual_go.setEnabled(False)
                self.manual_hit.setText(f'{enemy.name}: полное укрытие, цель недоступна')
                self.map_view.set_cover_overlay(enemy, cover)
                return
            self._manual_target = enemy
            self.manual_go.setEnabled(True)
            self.selected = enemy
            self.map_view.rebuild(self.battle_map, self.sides, self._manual_actor)
            self._refresh_manual_hit()
            if cover:
                from terrain import COVER_LABEL
                self.manual_hit.setText(f'{self.manual_hit.text()} · {COVER_LABEL[cover]}')
                self.map_view.set_cover_overlay(enemy, cover)
            return
        if self._manual_kind != 'effect':
            return
        placement = self._manual_placement
        effect = self._manual_effect
        if (effect is not None and effect.get('choice') and placement is not None
                and enemy in placement.creatures):
            if self._manual_include is None:
                self._refresh_manual_hit()
            if enemy in self._manual_include:
                self._manual_include = [item for item in self._manual_include if item is not enemy]
            else:
                self._manual_include = list(self._manual_include) + [enemy]
            self._refresh_manual_hit()
            return
        pos = self.battle_map.get_pos(enemy) if self.battle_map is not None else None
        if pos is not None:
            self._aim_locked = True
            self._manual_aim(pos)

    def _manual_confirm(self):
        kind = getattr(self, '_manual_kind', None)
        if kind == 'attack':
            self._manual_order = battle_round.ManualAction(
                'attack', attack=self._manual_attack, target=self._manual_target)
        elif kind == 'effect':
            include = self._manual_include if (
                self._manual_effect is not None and self._manual_effect.get('choice')) else None
            self._manual_order = battle_round.ManualAction(
                'effect', effect=self._manual_effect, placement=self._manual_placement,
                include=include)
        else:
            self._manual_order = battle_round.ManualAction('skip')
        self._close_manual_ui()

    def _manual_as_ai(self):
        self._manual_order = battle_round.ManualAction('auto')
        self._close_manual_ui()

    def _manual_skip_turn(self):
        self._manual_order = battle_round.ManualAction('skip')
        self._close_manual_ui()

    @staticmethod
    def _area_cells(events):
        seen = set()
        cells = []
        for event in events or []:
            if getattr(event, 'result', None) != 'area':
                continue
            for cell in event.area_cells or []:
                if cell is None or len(cell) < 2:
                    continue
                key = (int(cell[0]), int(cell[1]))
                if key not in seen:
                    seen.add(key)
                    cells.append(key)
        return cells

    def selected_enemies(self):
        out = []
        for i, checks in enumerate(self.side_checks):
            for j, cb in enumerate(checks):
                if cb.isChecked() and j < len(self.sides[i]):
                    out.append(self.sides[i][j])
        return out

    def mass_edit(self):
        enemies = self.selected_enemies()
        if not enemies:
            QMessageBox.warning(self, 'Внимание', 'Выберите хотя бы одно существо!')
            return
        self.open_creature_sheet(enemies)

    def edit_one(self, enemy):
        if enemy is None:
            return
        self.open_creature_sheet([enemy])

    def open_creature_sheet(self, enemies):
        enemies = [enemy for enemy in enemies if enemy is not None]
        if not enemies:
            return None
        sheet = CreatureSheet(self, enemies, self._side_labels())
        sheet.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        sheet.applied.connect(lambda _checked=False, who=sheet: self._on_sheet_applied(who))
        sheet.destroyed.connect(lambda *_args, who=sheet: self._forget_sheet(who))
        self._sheets.append(sheet)
        sheet.show()
        sheet.raise_()
        sheet.activateWindow()
        return sheet

    def _forget_sheet(self, sheet):
        self._sheets = [item for item in self._sheets if item is not sheet]

    def _close_sheets_for(self, enemy):
        for sheet in list(self._sheets):
            if enemy in getattr(sheet, 'enemies', ()):
                sheet.close()

    def _on_sheet_applied(self, sheet):
        enemies = [enemy for enemy in sheet.enemies if self._holds(enemy)]
        if not enemies:
            return
        label = (f'правка: {enemies[0].name}' if len(enemies) == 1
                 else f'правка: {len(enemies)} существ')
        sheet.write_creatures()
        self._reassign_side(enemies, sheet.chosen_side())
        focus = enemies[0]
        self.selected = focus
        self._refresh_roster(focus)
        self._commit(label)
        self.status.showMessage(f'Карточка применена: {focus.name}')

    def _holds(self, enemy):
        return any(enemy in side for side in self.sides)

    def _side_labels(self):
        if self.side_names:
            return list(self.side_names)
        if self.cards:
            return [card['name'].text().strip() or f'Сторона {chr(65 + i)}'
                    for i, card in enumerate(self.cards)]
        return ['Сторона A']

    def _ensure_side(self, index):
        if index < 0:
            index = len(self.sides)
        while len(self.sides) <= index:
            i = len(self.sides)
            if i < len(self.cards):
                name = self.cards[i]['name'].text().strip() or f'Сторона {chr(65 + i)}'
            elif i < 26:
                name = f'Сторона {chr(65 + i)}'
            else:
                name = f'Сторона {i + 1}'
            self.sides.append([])
            self.side_names.append(name)
        while len(self.side_names) < len(self.sides):
            i = len(self.side_names)
            self.side_names.append(f'Сторона {chr(65 + i)}' if i < 26 else f'Сторона {i + 1}')
        return index

    def _ensure_map(self):
        if self.battle_map is None:
            self.battle_map = BattleMap(24, 16)
        return self.battle_map

    def _nearest_free(self, enemy, x, y):
        battle_map = self.battle_map
        if battle_map is None:
            return None

        def snap(value):
            return round(float(value) * 2) / 2

        x, y = snap(x), snap(y)
        if battle_map.cell_free(x, y, enemy=enemy):
            return x, y
        limit = max(battle_map.width, battle_map.height) * 2
        for radius in range(1, limit + 1):
            for dx in range(-radius, radius + 1):
                for dy in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    nx, ny = snap(x + dx * 0.5), snap(y + dy * 0.5)
                    if battle_map.cell_free(nx, ny, enemy=enemy):
                        return nx, ny
        return None

    def _refresh_roster(self, focus=None):
        self.rebuild_battle_lists()
        self.refresh_alliances()
        self.log_panel.set_roster(self.sides, self.side_names)
        self._refresh_initiative()
        if focus is not None:
            self.set_selection([focus])
            return
        self.selection = [enemy for enemy in self.selection if self._holds(enemy)]
        if self.selected not in self.selection:
            self.selected = self.selection[-1] if self.selection else None
        self._sync_selection_widgets()
        self._note_selection()

    def _unique_name(self, base):
        existing = {enemy.name for side in self.sides for enemy in side}
        if base not in existing:
            return base
        candidate = f'{base} (копия)'
        number = 2
        while candidate in existing:
            candidate = f'{base} (копия {number})'
            number += 1
        return candidate

    def prompt_add_creature(self, x=None, y=None, type_name=None):
        # Кнопка и пункт меню передают bool от clicked/triggered — это не координата.
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            x = None
        if isinstance(y, bool) or not isinstance(y, (int, float)):
            y = None
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return None
        dialog = AddCreatureDialog(
            self, types_available(), self._side_labels(),
            cell=None if x is None or y is None else (x, y),
            current_type=type_name)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        data = dialog.result_data()
        if not data['name'] or not data['type']:
            QMessageBox.warning(self, 'Существо', 'Нужны имя и состав.')
            return None
        if x is None or y is None:
            x, y = 1, 1
        return self.add_creature_at(x, y, data['type'], data['side'], data['name'],
                                    data['strategy'])

    def add_creature_at(self, x, y, type_name, side=0, name=None, strategy='случайная'):
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return None
        side = self._ensure_side(side)
        name = (name or f'{type_name} {len(self.sides[side]) + 1}').strip()
        name = self._unique_name(name)
        enemy = EnemyFactory.create_enemy(type_name, name, side)
        enemy.strategy = make_strategy(strategy)
        self._ensure_map()
        spot = self._nearest_free(enemy, x, y)
        if spot is None:
            QMessageBox.warning(self, 'Карта', 'Нет свободного места для существа.')
            return None
        self.sides[side].append(enemy)
        self.battle_map.place(enemy, spot[0], spot[1])
        enemy.moved_ft = 0
        self.selected = enemy
        self._refresh_roster(enemy)
        self._commit(f'существо: {enemy.name}')
        self.status.showMessage(f'На карте: {enemy.name}')
        return enemy

    def duplicate_enemy(self, enemy):
        if enemy is None or not self._holds(enemy) or self._manual_loop is not None:
            return None
        import copy
        from entities import Enemy
        data = copy.deepcopy(enemy.to_dict())
        data['name'] = self._unique_name(enemy.name)
        data.pop('uid', None)
        clone = Enemy.from_dict(data)
        clone.initiative_bonus = int(getattr(enemy, 'initiative_bonus', 0) or 0)
        side = self._ensure_side(int(getattr(enemy, 'side', 0) or 0))
        clone.side = side
        self._ensure_map()
        origin = self.battle_map.get_pos(enemy) or (0, 0)
        spot = self._nearest_free(clone, origin[0] + 1, origin[1])
        if spot is None:
            QMessageBox.warning(self, 'Карта', 'Нет свободного места для копии.')
            return None
        self.sides[side].append(clone)
        self.battle_map.place(clone, spot[0], spot[1])
        clone.moved_ft = 0
        self.selected = clone
        self._refresh_roster(clone)
        self._commit(f'дублирование {enemy.name}')
        self.status.showMessage(f'Копия: {clone.name}')
        return clone

    def delete_enemy(self, enemy):
        if enemy is None or not self._holds(enemy):
            return False
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return False
        answer = QMessageBox.question(
            self, 'Удалить существо?', f'Удалить «{enemy.name}» с карты?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        name = enemy.name
        for side in self.sides:
            if enemy in side:
                side.remove(enemy)
                break
        if self.battle_map is not None:
            self.battle_map.unplace(enemy)
        self.selection = [item for item in self.selection if item is not enemy]
        if self.selected is enemy:
            self.selected = None
            if self.selection:
                self.selected = self.selection[-1]
        if self._relocate is enemy:
            self._relocate = None
        self._close_sheets_for(enemy)
        self._refresh_roster(None)
        self._commit(f'удаление {name}')
        self.status.showMessage(f'Удалено: {name}')
        return True

    def change_enemy_side(self, enemy, side_index):
        if enemy is None or not self._holds(enemy) or self._manual_loop is not None:
            return
        self._reassign_side([enemy], side_index)
        self.selected = enemy
        self._refresh_roster(enemy)
        side_name = self.side_names[enemy.side] if enemy.side < len(self.side_names) else ''
        self._commit(f'сторона: {enemy.name}')
        self.status.showMessage(f'{enemy.name} → {side_name}')

    def _reassign_side(self, enemies, side_index):
        side_index = self._ensure_side(side_index)
        for enemy in list(enemies):
            if enemy.side == side_index and enemy in self.sides[side_index]:
                continue
            for row in self.sides:
                if enemy in row:
                    row.remove(enemy)
            self.sides[side_index].append(enemy)
            enemy.side = side_index

    def clear_field(self):
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return
        if not any(self.sides):
            self.status.showMessage('На карте нет существ.')
            return
        answer = QMessageBox.question(
            self, 'Очистить поле?',
            'Убрать всех существ с карты? Шаблоны сторон в окне «Стороны» останутся.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        for side in self.sides:
            side.clear()
        self.selected = None
        self.selection = []
        self._relocate = None
        self._relocate_group = None
        for sheet in list(self._sheets):
            sheet.close()
        if self.battle_map is not None:
            old_map = self.battle_map
            self.battle_map = BattleMap(old_map.width, old_map.height)
            self.battle_map.copy_terrain_from(old_map)
        self._refresh_roster(None)
        self._commit('очистка поля')
        self.status.showMessage('Поле очищено. Шаблоны сторон на месте.')

    def begin_relocate(self, enemy):
        if enemy is None or not self._holds(enemy):
            return
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return
        self._ensure_map()
        self._relocate = enemy
        self.on_token(enemy)
        self.status.showMessage(
            f'Кликните клетку — «{enemy.name}» встанет туда без затраты скорости. '
            'Esc отменяет.')

    def _finish_relocate(self, x, y):
        enemy = self._relocate
        group = [item for item in (self._relocate_group or []) if self._holds(item)]
        if len(group) > 1 and enemy in group:
            self._relocate = None
            self._relocate_group = None
            self.set_selection(group, primary=enemy)
            self.shift_group(enemy, x, y)
            return
        self._relocate_group = None
        if enemy is None or not self._holds(enemy):
            self._relocate = None
            return
        self._ensure_map()
        if not self.battle_map.cell_free(x, y, ignore_id=id(enemy), enemy=enemy):
            self.status.showMessage('Клетка занята. Выберите другую или нажмите Esc.')
            return
        previous = self.battle_map.get_pos(enemy)
        self.battle_map.place(enemy, x, y)
        placed = self.battle_map.get_pos(enemy)
        self._relocate = None
        if previous == placed:
            self.on_token(enemy)
            self.status.showMessage('Перемещение отменено: та же клетка.')
            return
        self.selected = enemy
        self.map_view.rebuild(self.battle_map, self.sides, enemy)
        self.on_token(enemy)
        self._commit(f'перемещение {enemy.name}')

    def _cancel_relocate(self):
        if self._relocate is None and not self._relocate_group:
            return
        name = self._relocate.name if self._relocate is not None else 'группа'
        self._relocate = None
        self._relocate_group = None
        self.status.showMessage(f'Перемещение «{name}» отменено.')

    def keyPressEvent(self, event):
        super().keyPressEvent(event)

    def show_status(self):
        lines = ['=== ТЕКУЩИЙ СТАТУС ===']
        for side, name in zip(self.sides, self.side_names):
            lines.append(f'{name}:')
            for e in side:
                st = '🟢 ЖИВ' if e.alive else '🔴 МЕРТВ'
                ign = ''
                if e.ignore_sides:
                    ign = ' (Игнорирует: ' + ', '.join(
                        self.side_names[s] for s in e.ignore_sides
                        if s < len(self.side_names)) + ')'
                lines.append(f'  {e.name}: {e.hp}/{e.max_hp} HP '
                             f'[{self._enemy_text(e).split("[")[-1]} ({st}){ign}')
            lines.append('')
        notes = self.log_panel.add_note('\n'.join(lines))
        self.battle_events.extend(notes)
        self._commit('статус')

    def clear_log(self):
        self.battle_events = []
        self.log_panel.clear()
        self.map_view.set_round_lines([])
        self.map_view.set_area_cells([])
        self.map_view.set_preview_cells([])
        self.map_view.set_focus_areas([])
        self._refresh_initiative()
        self._commit('очистка журнала')

    def copy_log(self):
        QApplication.clipboard().setText(render_log(self.battle_events))
        self.copy_btn.setText('✓ Скопировано')
        QTimer.singleShot(1200, lambda: self.copy_btn.setText('📋 Копировать лог'))

    def export_log(self):
        if not self.battle_events:
            QMessageBox.information(self, 'Экспорт', 'Журнал пуст — сначала проведите раунд.')
            return
        os.makedirs('battle_exports', exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        default = os.path.join('battle_exports', f'log_{stamp}.md')
        path, chosen = QFileDialog.getSaveFileName(
            self, 'Экспорт журнала боя', default,
            'Markdown (*.md);;Текст (*.txt);;JSON (*.json)')
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in ('.md', '.markdown', '.txt', '.json'):
            if chosen and 'JSON' in chosen:
                path += '.json'
            elif chosen and 'Текст' in chosen:
                path += '.txt'
            else:
                path += '.md'
        try:
            dump_log(self.battle_events, path)
        except OSError as exc:
            QMessageBox.critical(self, 'Экспорт', f'Не удалось записать файл: {exc}')
            return
        self.status.showMessage(f'Журнал сохранён: {path}')

    def on_log_entry(self, event):
        if self.battle_map is None:
            return
        involved = []
        seen = set()
        ids = []
        if event.kind == 'initiative':
            ids = [roll.actor_id for roll in event.rolls]
        else:
            ids = [event.actor_id, event.target_id]
            ids.extend(event.area_ids or [])
        for creature_id in ids:
            enemy = self._find_enemy(creature_id)
            if enemy is not None and id(enemy) not in seen:
                seen.add(id(enemy))
                involved.append(enemy)
        if involved:
            self.selected = involved[0]
            self.map_view.focus_creatures(involved)
            pos = self.battle_map.get_pos(involved[0])
            names = ' · '.join(enemy.name for enemy in involved[:4])
            extra = '' if len(involved) <= 4 else f' +{len(involved) - 4}'
            self.map_info.setText(f'{names}{extra} · клетка {pos}')
        self.map_view.set_focus_lines(
            map_marks([event], self._token_radius, include_moves=True))
        self.map_view.set_focus_areas(event.area_cells)
        who = event.actor or event.kind
        self.status.showMessage(f'Журнал: {who}' + (f' → {event.target}' if event.target else ''))

    def _find_enemy(self, creature_id):
        if creature_id is None:
            return None
        for side in self.sides:
            for enemy in side:
                if id(enemy) == creature_id:
                    return enemy
        return None

    def _token_radius(self, creature_id):
        enemy = self._find_enemy(creature_id)
        if enemy is None or self.battle_map is None:
            return 0.45
        return self.battle_map.cells_of(enemy) / 2

    def open_analysis(self):
        log = self.engine.get_round_log()
        d = QDialog(self)
        d.setWindowTitle('Анализ сражения — почему принято каждое решение')
        d.resize(880, 700)
        lay = QVBoxLayout(d)
        if not log:
            lab = QLabel('Раундов ещё не проводилось — проведите бой и откройте анализ.')
            lab.setProperty('role', 'muted')
            lay.addWidget(lab)
            d.exec()
            return
        head = QLabel(f'Решений за последний раунд: {len(log)}   ·   ✦ = магическое оружие')
        head.setProperty('role', 'title')
        lay.addWidget(head)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        host = QWidget()
        hl = QVBoxLayout(host)
        for s in log:
            int_txt = 'не указан' if s['int_score'] is None else str(s['int_score'])
            sec = Section(f"{s['unit']}  ·  INT={int_txt} → Tier {s['tier']} "
                          f"({s['tier_name']})  ·  {s['archetype']}")
            b = sec.body_lay
            for label, val in (
                    ('🎯 Цель', f"{s['target_name'] or '—'} · {s['target_reason']}"),
                    ('⚔️ Атака', s['attack_reason'] if s['multiattack'] else
                     f"{s['attack_name'] or 'мультиатака/делегат'} · {s['attack_reason']}"),
                    ('👣 Движение', f"{s['move_intent']} · {s['move_reason']}")):
                cap = QLabel(label)
                cap.setProperty('role', 'accent')
                txt = QLabel(val)
                txt.setWordWrap(True)
                b.addWidget(cap)
                b.addWidget(txt)
            if s['candidates']:
                cap = QLabel('📋 Разбор оружия (B1 дальность / B2 защиты / B3 EV):')
                cap.setProperty('role', 'accent')
                b.addWidget(cap)
                t = QTableWidget(len(s['candidates']), 6)
                t.setHorizontalHeaderLabels(['Атака', 'Reach', 'Тип', 'Eff', 'EV', 'Вердикт'])
                t.verticalHeader().setVisible(False)
                t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
                t.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
                t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                for r, cd in enumerate(s['candidates']):
                    verdict = ('✔ выбрана' if cd.get('chosen')
                               else (cd['reject'] or 'проиграла по EV/reach'))
                    for c, val in enumerate((cd['name'], cd['reach'], cd['dmg_type'],
                                             cd['eff'], cd['ev'], verdict)):
                        t.setItem(r, c, QTableWidgetItem(str(val)))
                t.setFixedHeight(min(220, 30 * (len(s['candidates']) + 1) + 10))
                b.addWidget(t)
            hl.addWidget(sec)
        hl.addStretch()
        sa.setWidget(host)
        lay.addWidget(sa, 1)
        close = QPushButton('Закрыть')
        close.setProperty('variant', 'outline')
        close.clicked.connect(d.accept)
        lay.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        d.exec()

    # ================= альянсы =================
    def _build_alliances(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.all_note = QLabel('Создайте армии (минимум 3 стороны), чтобы настроить альянсы.')
        self.all_note.setProperty('role', 'muted')
        lay.addWidget(self.all_note)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        self.all_host = QWidget()
        self.all_grid = QGridLayout(self.all_host)
        self.all_grid.setSpacing(6)
        sa.setWidget(self.all_host)
        sa.setMinimumHeight(220)
        lay.addWidget(sa, 1)
        lay.addWidget(self._outline('Применить альянсы', self.apply_alliances))
        return page

    def refresh_alliances(self):
        clear_layout(self.all_grid)
        self.all_vars = []
        n = len(self.side_names)
        if n < 3:
            self.all_note.setText('Для настройки альянсов требуется минимум 3 стороны.')
            return
        self.all_note.setText('Отметьте, какие стороны игнорируют друг друга, '
                              'затем нажмите «Применить альянсы».')
        for j, nm in enumerate(self.side_names):
            lab = QLabel(nm)
            lab.setProperty('role', 'accent')
            self.all_grid.addWidget(lab, 0, j + 1, Qt.AlignmentFlag.AlignCenter)
        for i, nm in enumerate(self.side_names):
            lab = QLabel(nm)
            lab.setProperty('role', 'accent')
            self.all_grid.addWidget(lab, i + 1, 0)
            row = []
            for j in range(n):
                if i == j:
                    self.all_grid.addWidget(QLabel('—'), i + 1, j + 1,
                                            Qt.AlignmentFlag.AlignCenter)
                    row.append(None)
                else:
                    cb = QCheckBox()
                    if (self.alliance_settings and i < len(self.alliance_settings)
                            and j < len(self.alliance_settings[i])):
                        cb.setChecked(bool(self.alliance_settings[i][j]))
                    self.all_grid.addWidget(cb, i + 1, j + 1, Qt.AlignmentFlag.AlignCenter)
                    row.append(cb)
            self.all_vars.append(row)
        self.all_grid.setRowStretch(len(self.side_names) + 1, 1)

    def apply_alliances(self):
        if not self.all_vars:
            QMessageBox.information(self, 'Альянсы', 'Сначала создайте армии (3+ стороны).')
            return
        self.alliance_settings, self.ignore_sides = [], {}
        for i, row in enumerate(self.all_vars):
            settings, ign = [], set()
            for j, cb in enumerate(row):
                on = bool(cb and cb.isChecked())
                settings.append(on)
                if on:
                    ign.add(j)
            self.alliance_settings.append(settings)
            self.ignore_sides[i] = ign
        for side in self.sides:
            for e in side:
                e.ignore_sides.clear()
        for i, ign in self.ignore_sides.items():
            for j in ign:
                for e in self.sides[i]:
                    e.ignore_sides.add(j)
        self.status.showMessage('Настройки альянсов применены.')
        self._commit('альянсы')

    # ================= карта + панель отображения =================
    def _slider(self, lo, hi, val, label, key, suffix=''):
        row = QVBoxLayout()
        cap = QLabel(f'{label}: {val}{suffix}')
        cap.setProperty('role', 'muted')
        s = QSlider(Qt.Orientation.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)

        def on_change(v):
            cap.setText(f'{label}: {v}{suffix}')
            self.map_view.set_opt(key, v)

        s.valueChanged.connect(on_change)
        row.addWidget(cap)
        row.addWidget(s)
        return row, s, cap

    def _build_display_section(self, lay):
        self._map_sliders = {}
        for key, label, lo, hi, suffix in (
                ('cell', 'Размер клетки', 16, 56, ' px'),
                ('zoom', 'Масштаб', 25, 300, ' %'),
                ('dead_alpha', 'Видимость павших', 10, 100, ' %'),
                ('stroke', 'Обводка токенов', 0, 4, ' px')):
            row, slider, cap = self._slider(lo, hi, DEFAULT_OPTS[key], label, key, suffix)
            lay.addLayout(row)
            self._map_sliders[key] = (slider, cap, label, suffix)

        self.cb_grid = QCheckBox('Сетка поля')
        self.cb_grid.setChecked(True)
        self.cb_grid.toggled.connect(lambda v: self.map_view.set_opt('grid', v))
        lay.addWidget(self.cb_grid)
        self.cb_reach = QCheckBox('Подсветка досягаемости')
        self.cb_reach.setChecked(True)
        self.cb_reach.toggled.connect(lambda v: self.map_view.set_opt('reach', v))
        lay.addWidget(self.cb_reach)
        self.cb_glow = QCheckBox('Свечение выбранного')
        self.cb_glow.setChecked(True)
        self.cb_glow.toggled.connect(lambda v: self.map_view.set_opt('glow', v))
        lay.addWidget(self.cb_glow)
        self.cb_attacks = QCheckBox('Линии атак')
        self.cb_attacks.setChecked(True)
        self.cb_attacks.setToolTip(
            'Последний раунд: красный — попадание, золотой — крит, '
            'серый пунктир — промах, фиолетовый — натуральная 1, зелёный — лечение')
        self.cb_attacks.toggled.connect(lambda v: self.map_view.set_opt('attack_lines', v))
        lay.addWidget(self.cb_attacks)

        lay.addWidget(QLabel('Подписи токенов:'))
        self.cmb_labels = QComboBox()
        self.cmb_labels.addItems(['Номер бойца', 'Имя стороны', 'Без подписей'])
        self.cmb_labels.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('labels', ['number', 'name', 'none'][i]))
        lay.addWidget(self.cmb_labels)

        lay.addWidget(QLabel('Палитра сторон:'))
        self.cmb_sides = QComboBox()
        self.cmb_sides.addItems(['Классическая', 'Неон', 'Пергамент'])
        self.cmb_sides.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('sides', ['classic', 'neon', 'parchment'][i]))
        lay.addWidget(self.cmb_sides)
        lay.addWidget(self._outline('Сбросить вид', self.reset_map_opts))
        lay.addWidget(self._outline('Случайный вид', self.randomize_map_opts))
        export = QPushButton('Экспорт PNG')
        export.setProperty('variant', 'primary')
        export.setCursor(Qt.CursorShape.PointingHandCursor)
        export.clicked.connect(self.export_map_png)
        lay.addWidget(export)

    def _build_background_section(self, lay):
        load = QPushButton('Загрузить изображение…')
        load.setCursor(Qt.CursorShape.PointingHandCursor)
        load.clicked.connect(self.load_map_background)
        lay.addWidget(load)
        self.bg_info = QLabel('Фон не задан. Можно перетащить картинку прямо на поле.')
        self.bg_info.setProperty('role', 'muted')
        self.bg_info.setWordWrap(True)
        lay.addWidget(self.bg_info)
        lay.addWidget(QLabel('Масштабирование фона:'))
        self.cmb_bg_mode = QComboBox()
        self.cmb_bg_mode.addItems(['Растянуть по карте', 'Вписать (с полями)',
                                   'Заполнить (обрезать)', 'Замостить'])
        self.cmb_bg_mode.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('bg_mode', BG_MODES[i]))
        lay.addWidget(self.cmb_bg_mode)
        row, slider, cap = self._slider(10, 100, DEFAULT_OPTS['bg_opacity'],
                                        'Непрозрачность фона', 'bg_opacity', ' %')
        lay.addLayout(row)
        self._map_sliders['bg_opacity'] = (slider, cap, 'Непрозрачность фона', ' %')
        clear = QPushButton('Убрать фон')
        clear.setProperty('variant', 'danger')
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self.clear_map_background)
        lay.addWidget(clear)

    def _build_map(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.map_view = MapView(self.theme.palette())
        self.map_view.token_clicked.connect(self.on_token)
        self.map_view.token_menu.connect(self.open_token_menu)
        self.map_view.cell_menu.connect(self.open_cell_menu)
        self.map_view.cell_clicked.connect(self.on_cell)
        self.map_view.token_dragged.connect(self.on_token_dragged)
        self.map_view.token_settled.connect(self.on_token_settled)
        self.map_view.marquee_chosen.connect(self.on_marquee)
        self.map_view.image_dropped.connect(self._apply_background_path)
        self.map_view.aim_moved.connect(self.on_aim)
        self.map_view.terrain_cell.connect(self.on_terrain_cell)
        self.map_view.terrain_stroke_finished.connect(self.finish_terrain_stroke)
        self.map_view.hover_target.connect(self.on_hover_target)
        self.map_view.setToolTip(
            'Колесо — зум. Рамка по пустому месту выделяет группу, Alt или средняя кнопка — панорама. '
            'Клик по токену — выбрать, Ctrl или Shift — добавить. '
            'Перетащи токен или кликни по зелёной клетке — ход. '
            'Правый щелчок по токену — карточка и действия, по пустой клетке — '
            'добавить существо. «Рельеф» на тулбаре рисует клетки. '
            'Ctrl+Z — отмена. Картинку можно бросить на поле.')
        lay.addWidget(self.map_view, 1)
        self.manual_bar = QFrame()
        self.manual_bar.setObjectName('manual_bar')
        self.manual_bar.setProperty('role', 'card')
        self.manual_bar.hide()
        bar_lay = QVBoxLayout(self.manual_bar)
        bar_lay.setContentsMargins(8, 6, 8, 6)
        bar_lay.setSpacing(4)
        self.manual_title = QLabel('Ход')
        self.manual_title.setProperty('role', 'title')
        bar_lay.addWidget(self.manual_title)
        pick = QHBoxLayout()
        self.manual_action = QComboBox()
        self.manual_action.setObjectName('manual_action')
        self.manual_action.currentIndexChanged.connect(lambda _index: self._apply_manual_action())
        pick.addWidget(self.manual_action, 1)
        self.manual_go = QPushButton('Выполнить')
        self.manual_go.setObjectName('manual_go')
        self.manual_go.setProperty('variant', 'primary')
        self.manual_ai = QPushButton('Как решит ИИ')
        self.manual_ai.setObjectName('manual_ai')
        self.manual_skip = QPushButton('Пропустить ход')
        self.manual_skip.setObjectName('manual_skip')
        self.manual_go.clicked.connect(self._manual_confirm)
        self.manual_ai.clicked.connect(self._manual_as_ai)
        self.manual_skip.clicked.connect(self._manual_skip_turn)
        for button in (self.manual_go, self.manual_ai, self.manual_skip):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            pick.addWidget(button)
        bar_lay.addLayout(pick)
        self.manual_hint = QLabel('')
        self.manual_hint.setWordWrap(True)
        self.manual_hint.setProperty('role', 'muted')
        self.manual_hit = QLabel('')
        self.manual_hit.setWordWrap(True)
        self.manual_hit.setObjectName('manual_hit')
        bar_lay.addWidget(self.manual_hint)
        bar_lay.addWidget(self.manual_hit)
        lay.addWidget(self.manual_bar)
        self._build_terrain_bar()
        lay.addWidget(self.terrain_bar)
        self.map_info = QLabel(
            'Токен не выбран. Правый щелчок по пустой клетке — добавить существо.')
        self.map_info.setProperty('role', 'muted')
        self.map_info.setContentsMargins(8, 0, 8, 6)
        lay.addWidget(self.map_info)
        return page

    def _build_terrain_bar(self):
        from terrain import KIND_LABEL, KINDS
        bar = QFrame()
        bar.setObjectName('terrain_bar')
        bar.setProperty('role', 'card')
        bar.hide()
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(6)
        title = QLabel('Рельеф')
        title.setProperty('role', 'title')
        lay.addWidget(title)
        self._terrain_group = QButtonGroup(self)
        self._terrain_group.setExclusive(True)
        swatch = {
            'wall': '#5c6574',
            'difficult': '#8a9a4a',
            'water': '#2e86ab',
            'half': '#e0b341',
            'three_quarters': '#e07a3d',
            'total': '#8e3d55',
        }
        short = {
            'wall': 'Стена',
            'difficult': 'Трудная',
            'water': 'Вода',
            'half': '½ укрытие',
            'three_quarters': '¾ укрытие',
            'total': 'Полное',
        }
        self._terrain_buttons = {}
        for kind in KINDS:
            button = QPushButton(short[kind])
            button.setObjectName(f'brush_{kind}')
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setToolTip(KIND_LABEL[kind])
            button.setStatusTip(KIND_LABEL[kind])
            color = swatch[kind]
            button.setStyleSheet(
                f'QPushButton {{ background: {color}; color: #ffffff; '
                f'border: 1px solid {color}; }}'
                f'QPushButton:checked {{ border: 2px solid #ffffff; font-weight: bold; }}')
            button.clicked.connect(lambda _checked=False, key=kind: self.set_terrain_brush(key))
            self._terrain_group.addButton(button)
            self._terrain_buttons[kind] = button
            lay.addWidget(button)
        self._terrain_buttons['wall'].setChecked(True)
        eraser = QPushButton('Ластик')
        eraser.setObjectName('brush_eraser')
        eraser.setCheckable(True)
        eraser.setCursor(Qt.CursorShape.PointingHandCursor)
        eraser.setToolTip('Стирает рельеф. Правая кнопка на карте тоже стирает.')
        eraser.clicked.connect(lambda _checked=False: self.set_terrain_brush('erase'))
        self._terrain_group.addButton(eraser)
        self._terrain_buttons['erase'] = eraser
        lay.addWidget(eraser)
        clear = QPushButton('Очистить')
        clear.setObjectName('brush_clear')
        clear.setProperty('variant', 'danger')
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.setToolTip('Убрать весь рельеф с карты')
        clear.clicked.connect(self.clear_terrain)
        lay.addWidget(clear)
        lay.addStretch()
        self.terrain_bar = bar

    def _on_terrain_button(self, checked):
        self.set_terrain_mode(bool(checked))

    def set_terrain_mode(self, on):
        on = bool(on)
        button = getattr(self, 'terrain_btn', None)
        action = getattr(self, 'act_terrain', None)
        for widget in (button, action):
            if widget is None:
                continue
            widget.blockSignals(True)
            widget.setChecked(on)
            widget.blockSignals(False)
        if getattr(self, 'terrain_bar', None) is not None:
            self.terrain_bar.setVisible(on)
        if getattr(self, 'map_view', None) is not None:
            self.map_view.set_terrain_mode(on and self._manual_loop is None)
        if on:
            self.status.showMessage(
                'Рельеф: протяните кисть по клеткам. Правая кнопка — ластик. '
                'Штрих отменяется целиком.')
        else:
            self.status.showMessage('Режим рельефа выключен.')

    def set_terrain_brush(self, kind):
        self._terrain_brush = kind
        button = self._terrain_buttons.get(kind)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def on_terrain_cell(self, x, y, erase):
        if self.battle_map is None or self._manual_loop is not None:
            return
        if not (0 <= int(x) < self.battle_map.width and 0 <= int(y) < self.battle_map.height):
            return
        kind = None if erase or self._terrain_brush == 'erase' else self._terrain_brush
        if self.battle_map.terrain_at(x, y) == kind:
            return
        self.battle_map.set_terrain(x, y, kind)
        self._terrain_dirty = True
        self.map_view.refresh_terrain()

    def finish_terrain_stroke(self):
        if not self._terrain_dirty:
            return
        self._terrain_dirty = False
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self._commit('рельеф')
        self.status.showMessage('Рельеф изменён.')

    def clear_terrain(self):
        if self.battle_map is None or not self.battle_map.has_terrain():
            self.status.showMessage('На карте нет рельефа.')
            return
        self.battle_map.clear_terrain()
        self._terrain_dirty = False
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self._commit('очистка рельефа')
        self.status.showMessage('Рельеф очищен.')

    def _apply_background_path(self, path):
        if not self.map_view.set_background(path):
            QMessageBox.critical(self, 'Фон карты',
                                 'Не удалось загрузить изображение:\n' + path)
            return
        self._sync_bg_info()
        self.status.showMessage(f'Фон карты загружен: {os.path.basename(path)}')

    def load_map_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, 'Выберите изображение карты', '',
            'Изображения (*.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff);;Все файлы (*.*)')
        if path:
            self._apply_background_path(path)

    def clear_map_background(self):
        self.map_view.clear_background()
        self._sync_bg_info()
        self.status.showMessage('Фон карты убран.')

    def _sync_bg_info(self):
        info = self.map_view.background_info()
        if info:
            name, w, h = info
            self.bg_info.setText(f'{name}\n{w}×{h} px · подгоняется под поле автоматически')
        else:
            self.bg_info.setText('Фон не задан. Можно перетащить картинку прямо на поле.')

    def _sync_map_controls(self):
        o = self.map_view.opts
        for key, (s, cap, label, suffix) in self._map_sliders.items():
            s.blockSignals(True)
            s.setValue(o[key])
            s.blockSignals(False)
            cap.setText(f'{label}: {o[key]}{suffix}')
        for cb, key in ((self.cb_grid, 'grid'), (self.cb_reach, 'reach'),
                        (self.cb_glow, 'glow'), (self.cb_attacks, 'attack_lines')):
            cb.blockSignals(True)
            cb.setChecked(o[key])
            cb.blockSignals(False)
        for cmb, key, order in ((self.cmb_labels, 'labels', ['number', 'name', 'none']),
                                (self.cmb_sides, 'sides', ['classic', 'neon', 'parchment']),
                                (self.cmb_bg_mode, 'bg_mode', BG_MODES)):
            cmb.blockSignals(True)
            cmb.setCurrentIndex(order.index(o[key]))
            cmb.blockSignals(False)
        self._sync_bg_info()

    def reset_map_opts(self):
        self.map_view.reset_opts()
        self._sync_map_controls()
        self.status.showMessage('Отображение карты сброшено (фон сохранён).')

    def randomize_map_opts(self):
        self.map_view.opts.update({
            'cell': random.randint(20, 46),
            'dead_alpha': random.randint(20, 90),
            'stroke': random.randint(0, 3),
            'grid': random.choice([True, False]),
            'reach': True,
            'glow': random.choice([True, False]),
            'labels': random.choice(['number', 'name', 'none']),
            'sides': random.choice(list(SIDE_PALETTES)),
            'bg_opacity': random.randint(55, 100),
        })
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self._sync_map_controls()
        self.status.showMessage('Случайный вид карты применён (фон не тронут).')

    def export_map_png(self):
        if self.battle_map is None:
            QMessageBox.information(self, 'Экспорт', 'Сначала создайте армии.')
            return
        os.makedirs('battle_exports', exist_ok=True)
        default = os.path.join('battle_exports',
                               f'map_{datetime.now().strftime("%Y%m%d_%H%M%S")}.png')
        path, _ = QFileDialog.getSaveFileName(self, 'Сохранить карту как PNG',
                                              default, 'PNG (*.png)')
        if not path:
            return
        if self.map_view.export_png(path):
            self.status.showMessage(f'Карта сохранена: {path}')
        else:
            QMessageBox.critical(self, 'Экспорт', 'Не удалось сохранить изображение.')

    def place_random(self):
        if self.battle_map is None:
            return
        self.battle_map.random_placement(self.sides)
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self.status.showMessage('Случайная расстановка выполнена.')
        self._commit('случайная расстановка')

    def place_formation(self):
        if self.battle_map is None:
            return
        self.battle_map.formation_placement(self.sides)
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        self.status.showMessage('Расстановка строем выполнена.')
        self._commit('расстановка строем')

    def set_selection(self, enemies, primary=None, *, extend=False):
        cleaned = []
        seen = set()
        pool = list(self.selection) if extend else []
        for enemy in pool + list(enemies or []):
            if enemy is None or id(enemy) in seen or not self._holds(enemy):
                continue
            seen.add(id(enemy))
            cleaned.append(enemy)
        if primary is not None and primary in cleaned:
            cleaned = [enemy for enemy in cleaned if enemy is not primary] + [primary]
        self.selection = cleaned
        self.selected = cleaned[-1] if cleaned else None
        self._sync_selection_widgets()
        self._note_selection()

    def toggle_selection(self, enemy):
        if enemy in self.selection:
            rest = [item for item in self.selection if item is not enemy]
            self.set_selection(rest)
        else:
            self.set_selection([enemy], primary=enemy, extend=True)

    def clear_selection(self):
        self._keep_group = None
        self.set_selection([])
        self.status.showMessage('Выделение снято')

    def select_all_tokens(self):
        self.set_selection([enemy for side in self.sides for enemy in side])
        self.status.showMessage(f'Выделено: {len(self.selection)}')

    def select_side(self, index):
        if index < 0 or index >= len(self.sides):
            return
        self.set_selection(list(self.sides[index]))
        name = self.side_names[index] if index < len(self.side_names) else str(index + 1)
        self.status.showMessage(f'Выделена сторона: {name} ({len(self.selection)})')

    def _on_escape(self):
        if self._relocate is not None or self._relocate_group:
            self._cancel_relocate()
            return
        if self.selection:
            self.clear_selection()

    def _sync_selection_widgets(self):
        count = len(self.selection)
        if getattr(self, '_sel_label', None) is not None:
            self._sel_label.setText(f'Выделено: {count}')
        if getattr(self, 'map_view', None) is not None:
            self.map_view.rebuild(self.battle_map, self.sides, self.selected, self.selection)
        if getattr(self, 'map_info', None) is not None:
            if self.selected is not None:
                self.map_info.setText(self._token_line(self.selected))
            elif count == 0:
                self.map_info.setText(
                    'Никто не выделен. Рамка по пустому месту или Ctrl+клик — несколько.')
        self._sync_checks()
        self._mark_initiative_selection()

    def _sync_checks(self):
        chosen = {id(enemy) for enemy in self.selection}
        checks_rows = getattr(self, 'side_checks', None) or []
        for index, checks in enumerate(checks_rows):
            side = self.sides[index] if index < len(self.sides) else []
            marked = 0
            for box, enemy in zip(checks, side):
                box.blockSignals(True)
                box.setChecked(id(enemy) in chosen)
                box.blockSignals(False)
                if id(enemy) in chosen:
                    marked += 1
                label = self.enemy_labels.get(enemy)
                if label is not None:
                    if id(enemy) in chosen:
                        label.setStyleSheet(
                            'background: rgba(88, 101, 242, 0.38); border-radius: 4px; '
                            'padding: 1px 4px;')
                    else:
                        label.setStyleSheet('')
            all_rows = getattr(self, 'side_all_checks', None) or []
            if index >= len(all_rows):
                continue
            master = all_rows[index]
            master.blockSignals(True)
            if not side or marked == 0:
                master.setCheckState(Qt.CheckState.Unchecked)
            elif marked >= len(list(zip(checks, side))):
                master.setCheckState(Qt.CheckState.Checked)
            else:
                master.setCheckState(Qt.CheckState.PartiallyChecked)
            master.blockSignals(False)

    def _roster_press(self, event, enemy, widget):
        if event.button() == Qt.MouseButton.LeftButton:
            mods = event.modifiers()
            if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                self.toggle_selection(enemy)
            else:
                self.set_selection([enemy])
        QLabel.mousePressEvent(widget, event)

    def _on_roster_check(self, enemy, on):
        if on and enemy not in self.selection:
            self.set_selection([enemy], primary=enemy, extend=True)
        elif not on and enemy in self.selection:
            self.set_selection([item for item in self.selection if item is not enemy])

    def _on_side_toggle(self, index, checked):
        if index < 0 or index >= len(self.sides):
            return
        side = list(self.sides[index])
        if checked:
            self.set_selection(side, extend=True)
        else:
            drop = {id(enemy) for enemy in side}
            self.set_selection([enemy for enemy in self.selection if id(enemy) not in drop])

    def _fill_side_select_menu(self):
        menu = getattr(self, '_side_select_menu', None)
        if menu is None:
            return
        menu.clear()
        if not self.sides:
            empty = menu.addAction('нет сторон')
            empty.setEnabled(False)
            return
        for index, name in enumerate(self.side_names):
            count = len(self.sides[index]) if index < len(self.sides) else 0
            menu.addAction(
                f'{name} ({count})',
                lambda _checked=False, idx=index: self.select_side(idx))

    def shift_group(self, anchor, x, y):
        """Сдвиг всей группы на вектор от якоря до клетки. Один шаг отмены."""
        if anchor is None or self.battle_map is None or not self._holds(anchor):
            return False
        origin = self.battle_map.get_pos(anchor)
        if origin is None:
            return False
        dx, dy = float(x) - float(origin[0]), float(y) - float(origin[1])
        members = [enemy for enemy in self.selection
                   if self._holds(enemy) and self.battle_map.get_pos(enemy)]
        if len(members) < 2 or anchor not in members:
            return False
        if abs(dx) < 1e-9 and abs(dy) < 1e-9:
            self.status.showMessage('Группа уже здесь.')
            return False
        if not self.battle_map.try_shift_group(members, dx, dy):
            self.status.showMessage(
                'Группу нельзя поставить: нужна свободная проходимая клетка каждому.')
            self._sync_selection_widgets()
            return False
        self._sync_selection_widgets()
        self._commit(f'перемещение группы ({len(members)})')
        self.status.showMessage(f'Группа сдвинута: {len(members)}')
        return True

    def begin_relocate_group(self, enemies):
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        if len(enemies) < 2:
            if enemies:
                self.begin_relocate(enemies[0])
            return
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return
        self._ensure_map()
        self.set_selection(enemies, primary=enemies[0])
        self._relocate_group = list(enemies)
        self._relocate = enemies[0]
        self.status.showMessage(
            f'Кликните клетку — группа из {len(enemies)} встанет туда, форма сохранится. Esc отменяет.')

    def duplicate_group(self, enemies):
        import copy
        from entities import Enemy
        enemies = [enemy for enemy in enemies if self._holds(enemy) and self._manual_loop is None]
        if not enemies or self._manual_loop is not None:
            return []
        self._ensure_map()
        created = []
        for enemy in enemies:
            data = copy.deepcopy(enemy.to_dict())
            data['name'] = self._unique_name(enemy.name)
            data.pop('uid', None)
            clone = Enemy.from_dict(data)
            clone.initiative_bonus = int(getattr(enemy, 'initiative_bonus', 0) or 0)
            side = self._ensure_side(int(getattr(enemy, 'side', 0) or 0))
            clone.side = side
            origin = self.battle_map.get_pos(enemy) or (0, 0)
            spot = self._nearest_free(clone, origin[0] + 1, origin[1])
            if spot is None:
                for clone_done in created:
                    for row in self.sides:
                        if clone_done in row:
                            row.remove(clone_done)
                    self.battle_map.unplace(clone_done)
                QMessageBox.warning(self, 'Карта', 'Не хватает места, чтобы скопировать группу.')
                self._refresh_roster(None)
                return []
            self.sides[side].append(clone)
            self.battle_map.place(clone, spot[0], spot[1])
            clone.moved_ft = 0
            created.append(clone)
        self._refresh_roster(None)
        self.set_selection(created)
        self._commit(f'дублирование группы ({len(created)})')
        self.status.showMessage(f'Скопировано: {len(created)}')
        return created

    def delete_group(self, enemies):
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        if not enemies:
            return False
        if len(enemies) == 1:
            return self.delete_enemy(enemies[0])
        if self._manual_loop is not None:
            self.status.showMessage('Сначала закончите ручной ход.')
            return False
        answer = QMessageBox.question(
            self, 'Удалить группу?',
            f'Удалить {len(enemies)} существ с карты?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        for enemy in enemies:
            for side in self.sides:
                if enemy in side:
                    side.remove(enemy)
                    break
            if self.battle_map is not None:
                self.battle_map.unplace(enemy)
            self._close_sheets_for(enemy)
        self._relocate = None
        self._relocate_group = None
        self.selection = []
        self.selected = None
        self._refresh_roster(None)
        self._commit(f'удаление группы ({len(enemies)})')
        self.status.showMessage(f'Удалено: {len(enemies)}')
        return True

    def change_group_side(self, enemies, side_index):
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        if not enemies or self._manual_loop is not None:
            return
        self._reassign_side(enemies, side_index)
        self._refresh_roster(None)
        self.set_selection(enemies, primary=enemies[0])
        self._commit(f'сторона группы ({len(enemies)})')
        self.status.showMessage(f'Сторона изменена у {len(enemies)}')

    def damage_group(self, enemies):
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        if not enemies:
            return
        amount, ok = QInputDialog.getInt(
            self, 'Урон группе', f'Урон каждому из {len(enemies)}:', 1, 0, 9999, 1)
        if not ok:
            return
        for enemy in enemies:
            enemy.take_damage(int(amount))
        self._refresh_roster(None)
        self.set_selection(enemies)
        self._commit(f'урон группе ({len(enemies)})')
        self.status.showMessage(f'Урон {amount} — {len(enemies)} существ')

    def heal_group(self, enemies):
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        if not enemies:
            return
        amount, ok = QInputDialog.getInt(
            self, 'Лечение группы', f'Хиты каждому живому из {len(enemies)}:', 1, 0, 9999, 1)
        if not ok:
            return
        healed = 0
        for enemy in enemies:
            if enemy.heal(int(amount)):
                healed += 1
        self._refresh_roster(None)
        self.set_selection(enemies)
        self._commit(f'лечение группы ({len(enemies)})')
        self.status.showMessage(f'Лечение {amount}: получили {healed} из {len(enemies)}')

    def _impose_group(self, enemies, condition_id):
        from conditions import apply_condition, permanent_duration
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        changed = 0
        for enemy in enemies:
            if apply_condition(enemy, condition_id, duration=permanent_duration(),
                               note='вручную') is not None:
                changed += 1
        if not changed:
            self.status.showMessage('Никто не получил состояние')
            return
        self.refresh_all_labels()
        self._sync_selection_widgets()
        self._commit(f'состояние группе ({changed})')
        self.status.showMessage(f'Состояние наложено: {changed}')

    def _exhaust_group(self, enemies, level):
        from conditions import set_exhaustion
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        for enemy in enemies:
            set_exhaustion(enemy, level)
        self.refresh_all_labels()
        self._sync_selection_widgets()
        self._commit(f'истощение группе ({len(enemies)})')

    def _lift_group(self, enemies, condition_id):
        from conditions import active_conditions, remove_condition
        enemies = [enemy for enemy in enemies if self._holds(enemy)]
        changed = 0
        for enemy in enemies:
            current = [item for item in active_conditions(enemy)
                       if isinstance(item, dict) and item.get('id') == condition_id]
            for item in current:
                remove_condition(enemy, cond=item, reason='снято вручную')
                changed += 1
        if not changed:
            self.status.showMessage('Снимать нечего')
            return
        self.refresh_all_labels()
        self._sync_selection_widgets()
        self._commit(f'снято состояние группе ({changed})')

    def on_token(self, enemy):
        if self._manual_loop is not None:
            self._manual_click_token(enemy)
            return
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.toggle_selection(enemy)
            return
        if enemy in self.selection and len(self.selection) > 1:
            self._keep_group = enemy
            self.selected = enemy
            self._sync_selection_widgets()
            self._note_selection()
            return
        self._keep_group = None
        self.set_selection([enemy])

    def on_token_settled(self, enemy):
        """Клик без протягивания по уже выделенному в группе оставляет только его."""
        if self._manual_loop is not None:
            return
        if self._keep_group is enemy:
            self._keep_group = None
            self.set_selection([enemy])

    def on_marquee(self, enemies):
        if self._manual_loop is not None or self._aiming_blocks_marquee():
            return
        mods = QApplication.keyboardModifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            self.set_selection(enemies, extend=True)
        else:
            self.set_selection(enemies)
        count = len(self.selection)
        self.status.showMessage(f'Выделено: {count}' if count else 'Выделение снято')

    def _aiming_blocks_marquee(self):
        return bool(getattr(self.map_view, '_aiming', False))

    def on_token_dragged(self, enemy, x, y):
        if self._manual_loop is not None or enemy is None:
            return
        self._keep_group = None
        if len(self.selection) > 1 and enemy in self.selection:
            self.shift_group(enemy, x, y)
            return
        self.set_selection([enemy])
        self.on_cell(x, y)

    def on_cell(self, x, y):
        if self._manual_loop is not None:
            self._manual_click_cell(x, y)
            return
        if self._relocate is not None:
            self._finish_relocate(x, y)
            return
        if self.battle_map is None or self.selected is None or not self.selected.alive:
            return
        pos = self.battle_map.get_pos(self.selected)
        if not pos:
            return
        if self.battle_map.has_terrain():
            snapped = self.battle_map.snap_move(self.selected, x, y)
            dest, dist = snapped
            if dest is None:
                self.status.showMessage('Туда не пройти: стена или нет пути.')
                return
            x, y = dest
        else:
            dist = max(abs(x - pos[0]), abs(y - pos[1])) * 5
        if dist == 0:
            return
        from conditions import effective_speed, has_condition, is_incapacitated, try_stand
        speed_now = effective_speed(self.selected)
        if has_condition(self.selected, 'prone') and not is_incapacitated(self.selected):
            try_stand(self.selected)
        left = speed_now - getattr(self.selected, 'moved_ft', 0)
        if dist > left:
            QMessageBox.information(self, 'Движение',
                                    f'Не хватает скорости: нужно {dist} фт, осталось {left} фт')
            return
        if not self.battle_map.cell_free(x, y, ignore_id=id(self.selected),
                                         enemy=self.selected):
            return
        self.battle_map.place(self.selected, x, y)
        self.selected.moved_ft = getattr(self.selected, 'moved_ft', 0) + dist
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        name = self.selected.name
        self.on_token(self.selected)
        self._commit(f'ход {name}')

    def _apply_crit_mode(self, value):
        mode = normalize_crit_mode(value)
        idx = self.crit_mode.findData(mode)
        self.crit_mode.setCurrentIndex(idx if idx >= 0 else 0)

    # ================= настройки =================
    def save_settings(self):
        try:
            os.makedirs('battle_settings', exist_ok=True)
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            path = os.path.join('battle_settings', f'battle_{stamp}.json')
            data = {
                'num_sides': len(self.cards),
                'side_names': [c['name'].text() for c in self.cards],
                'side_counts': [c['count'].value() for c in self.cards],
                'army_types': [c['type'] for c in self.cards],
                'strategy_types': [c['strat'].currentText() for c in self.cards],
                'custom_types': dict(EnemyFactory.CUSTOM_TYPES),
                'alliance_settings': self.alliance_settings,
                'ignore_sides': {str(k): list(v) for k, v in self.ignore_sides.items()},
                'crit_mode': self.crit_mode.currentData() or 'double_all',
                'hide_hp': bool(self.hide_hp.isChecked()),
                'map_opts': dict(self.map_view.opts),
                'map_bg': self.map_view.background_path,
                'battle': capture_battle(self),
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status.showMessage(f'Настройки сохранены: {path}')
        except Exception as e:
            QMessageBox.critical(self, 'Ошибка', f'Ошибка при сохранении: {e}')

    def load_settings(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Выберите файл настроек',
                                              'battle_settings', 'JSON files (*.json)')
        if not path:
            return
        self._suspend_history = True
        try:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                for name, td in (data.get('custom_types') or {}).items():
                    EnemyFactory.CUSTOM_TYPES[name] = td
                self._discard_cards()
                names = data.get('side_names') or []
                counts = data.get('side_counts') or []
                types = data.get('army_types') or []
                strats = data.get('strategy_types') or []
                n = int(data.get('num_sides') or len(names) or 2)
                fallback = types_available()[0]
                for i in range(n):
                    self.add_card(types[i] if i < len(types) else fallback,
                                  strats[i] if i < len(strats) else 'случайная',
                                  names[i] if i < len(names) else None,
                                  counts[i] if i < len(counts) else 5)
                self._apply_crit_mode(data.get('crit_mode'))
                if 'hide_hp' in data:
                    self.hide_hp.setChecked(bool(data.get('hide_hp')))
                self.alliance_settings = data.get('alliance_settings') or []
                self.ignore_sides = {int(k): set(v)
                                     for k, v in (data.get('ignore_sides') or {}).items()}
                opts = data.get('map_opts')
                if opts:
                    self.map_view.opts.update({k: v for k, v in opts.items()
                                               if k in DEFAULT_OPTS})
                bg = data.get('map_bg')
                if bg and os.path.exists(bg):
                    self.map_view.set_background(bg)
                else:
                    self.map_view.clear_background()
                self.map_view.set_opt('zoom', self.map_view.opts['zoom'])
                self._sync_map_controls()
                self.cols = 0
                self.relayout_cards()
                battle = data.get('battle')
                if isinstance(battle, dict) and battle.get('sides'):
                    info = apply_snapshot(battle, self)
                    self.rebuild_battle_lists()
                    self.refresh_alliances()
                    self.log_panel.set_roster(self.sides, self.side_names)
                    if info.events_changed:
                        self.log_panel.load_events(self.battle_events)
                    self.selected = info.selected
                    self.map_view.rebuild(self.battle_map, self.sides, self.selected)
                    self._refresh_initiative()
                    self.status.showMessage(
                        f'Бой загружен: сторон {len(self.sides)}, '
                        f'раунд {self.round_no}.')
                else:
                    self.status.showMessage(
                        f'Настройки загружены: сторон {n}. Нажмите «Создать армии».')
            except Exception as e:
                QMessageBox.critical(self, 'Ошибка', f'Ошибка при загрузке: {e}')
                return
        finally:
            self._suspend_history = False
        self.history.clear()
        self._current = capture_battle(self)
        self._sync_history_actions()


def main():
    app = QApplication(sys.argv)
    qt_async.install(app)
    win = MainWindow()
    win.showMaximized()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()