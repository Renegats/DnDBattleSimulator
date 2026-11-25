"""Qt-фронтенд симулятора: полное приложение на общем ядре.

Карта боя имеет постоянно видимую панель отображения (живые настройки + экспорт).
"""
import json
import os
import random
import sys
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QKeySequence, QPixmap
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QGridLayout, QLabel, QLineEdit, QSpinBox,
                             QComboBox, QPushButton, QCheckBox,
                             QScrollArea, QSplitter, QStackedWidget, QGroupBox, QFrame,
                             QMessageBox, QFileDialog, QDialog, QTableWidget,
                             QTableWidgetItem, QHeaderView, QButtonGroup, QSlider)

import battle_round
from battle_history import BattleHistory, apply_snapshot, capture_battle, ensure_uid
from battle_strategies import (AggressiveStrategy, DefensiveStrategy,
                               RandomStrategy, SupportStrategy)
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
from qt_editors import SideCreatorDialog, CreatureEditDialog, Section, STRATS

try:
    from battle_map_model import BattleMap
except ImportError:
    from battle_map import BattleMap

MAX_SIDES = 26


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
        self.cards, self.all_vars = [], []
        self.enemy_labels, self.side_checks = {}, []
        self.dirty, self.suspend = set(), False
        self.cols = 3
        self._icon_buttons = []
        self.history = BattleHistory()
        self._history_ready = False
        self._suspend_history = False
        self._current = None

        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(12, 8, 12, 0)
        v.setSpacing(6)

        top = QGridLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(2, 1)
        self._install_history_controls()
        left_host = QWidget()
        left = QHBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        left.addWidget(self.btn_undo)
        left.addWidget(self.btn_redo)
        left.addStretch()
        top.addWidget(left_host, 0, 0, Qt.AlignmentFlag.AlignLeft)
        nav_host = QWidget()
        nav = QHBoxLayout(nav_host)
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for i, name in enumerate(('Настройка армий', 'Битва', 'Альянсы', 'Карта боя')):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setMinimumWidth(152)
            b.setMinimumHeight(36)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.select_tab(idx))
            self.nav_group.addButton(b, i)
            nav.addWidget(b)
            self.nav_buttons.append(b)
        top.addWidget(nav_host, 0, 1, Qt.AlignmentFlag.AlignCenter)
        right_host = QWidget()
        right = QHBoxLayout(right_host)
        right.setContentsMargins(0, 0, 0, 0)
        right.addStretch()
        self.theme_btn = IconButton('moon' if self.theme.current == 'dark' else 'sun',
                                    self.theme.palette(), size=40)
        self.theme_btn.setToolTip('Переключить тему')
        self.theme_btn.clicked.connect(self.toggle_theme)
        right.addWidget(self.theme_btn)
        self._icon_buttons.append(self.theme_btn)
        top.addWidget(right_host, 0, 2)
        v.addLayout(top)

        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_battle())
        self.stack.addWidget(self._build_alliances())
        self.stack.addWidget(self._build_map())

        sep = QFrame()
        sep.setProperty('role', 'sep')
        sep.setFixedHeight(2)
        v.addWidget(sep)
        bar = QFrame()
        bar.setProperty('role', 'bar')
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 7, 10, 7)
        self.sub_holder = QHBoxLayout()
        self.sub_holder.setSpacing(6)
        bl.addStretch()
        bl.addLayout(self.sub_holder)
        bl.addStretch()
        v.addWidget(bar)

        self.status = self.statusBar()
        self.status.showMessage('Создайте армии на вкладке «Настройка армий».')
        self.add_card()
        self.add_card()
        self.select_tab(0)
        self._current = capture_battle(self)
        self._history_ready = True
        self._sync_history_actions()

    # ================= вкладки =================
    def select_tab(self, idx):
        self.stack.setCurrentIndex(idx)
        self.nav_buttons[idx].setChecked(True)
        clear_layout(self.sub_holder)
        tools = {
            0: [('Сохранить настройки', self.save_settings),
                ('Загрузить настройки', self.load_settings)],
            1: [('Показать статус', self.show_status),
                ('Очистить результаты', self.clear_log)],
            2: [('Применить настройки альянсов', self.apply_alliances)],
            3: [('🎲 Расставить случайно', self.place_random),
                ('🛡 Расставить строем', self.place_formation)],
        }[idx]
        for text, fn in tools:
            b = QPushButton(text)
            b.setProperty('variant', 'outline')
            b.setMinimumHeight(32)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            self.sub_holder.addWidget(b)

    def toggle_theme(self):
        name = self.theme.toggle()
        pal = self.theme.palette()
        self.theme_btn.set_kind('moon' if name == 'dark' else 'sun')
        for b in self._icon_buttons:
            b.set_palette(pal)
        for c in self.cards:
            c['frame'].set_palette(pal)
        self.map_view.set_palette(pal)
        self.status.showMessage(f'Тема: {"тёмная" if name == "dark" else "светлая"}')

    # ================= отмена / повтор =================
    def _install_history_controls(self):
        edit = self.menuBar().addMenu('Правка')
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

        self.btn_undo = QPushButton('Отменить')
        self.btn_redo = QPushButton('Повторить')
        for button, action in ((self.btn_undo, self.undo_action),
                               (self.btn_redo, self.redo_action)):
            button.setObjectName(action.objectName() + '_button')
            button.setMinimumHeight(32)
            button.setMinimumWidth(112)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(action.trigger)

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
        if self._current.get('selected_uid') == uid:
            return
        snap = dict(self._current)
        snap['selected_uid'] = uid
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
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
            self.map_view.set_round_lines(
                map_marks(self._latest_round_events(), self._token_radius))
            self.map_view.set_focus_lines([])
            if self.selected is not None:
                pos = None if self.battle_map is None else self.battle_map.get_pos(self.selected)
                left = self.selected.speed - getattr(self.selected, 'moved_ft', 0)
                self.map_info.setText(
                    f'{self.selected.name}: HP {self.selected.hp}/{self.selected.max_hp}, '
                    f'AC {self.selected.ac}, клетка {pos}, скорость {self.selected.speed} фт, '
                    f'остаток {left} фт')
            else:
                self.map_info.setText('Токен не выбран.')
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
        try:
            self.sides, self.side_names = [], []
            strat_cls = {'случайная': RandomStrategy, 'агрессивная': AggressiveStrategy,
                         'защитная': DefensiveStrategy, 'поддержка': SupportStrategy}
            for i, c in enumerate(self.cards):
                name = c['name'].text().strip() or f'Сторона {chr(65 + i)}'
                self.side_names.append(name)
                cls = strat_cls[c['strat'].currentText()]
                side = []
                for j in range(c['count'].value()):
                    e = EnemyFactory.create_enemy(c['type'], f'{name}_{j + 1}', i)
                    e.strategy = cls()
                    side.append(e)
                self.sides.append(side)
            n = len(self.sides)
            max_side = max((len(s) for s in self.sides), default=0)
            map_w = max(24, 4 * n)
            zone_cols = max(1, map_w // n)
            map_h = max(16, (max_side + zone_cols - 1) // zone_cols + 2)
            self.battle_map = BattleMap(width=map_w, height=map_h)
            self.ignore_sides = {}
            self.selected = None
            self.round_no = 0
            self.battle_events = []
            self.battle_map.formation_placement(self.sides)
            self.rebuild_battle_lists()
            self.refresh_alliances()
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
            self.map_view.set_round_lines([])
            self.log_panel.clear()
            self.log_panel.set_roster(self.sides, self.side_names)
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
    def _build_battle(self):
        page = QWidget()
        lay = QVBoxLayout(page)
        self.battle_scroll = QScrollArea()
        self.battle_scroll.setWidgetResizable(True)
        self.battle_host = QWidget()
        self.battle_lay = QVBoxLayout(self.battle_host)
        self.battle_scroll.setWidget(self.battle_host)
        lay.addWidget(self.battle_scroll, 2)
        self.log_panel = CombatLogPanel()
        self.log_panel.entry_activated.connect(self.on_log_entry)
        lay.addWidget(self.log_panel, 3)
        row = QHBoxLayout()
        for text, fn in (('▶  Провести раунд боя', self.run_round),
                         ('Массовое редактирование', self.mass_edit),
                         ('📋 Копировать лог', self.copy_log),
                         ('💾 Экспорт журнала', self.export_log),
                         ('🔍 Анализ сражения', self.open_analysis)):
            b = QPushButton(text)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            if text.startswith('▶'):
                b.setProperty('variant', 'primary')
                b.setMinimumHeight(38)
                self.round_btn = b
            if 'Копировать' in text:
                self.copy_btn = b
            row.addWidget(b)
        row.addStretch()
        self.auto_move = QCheckBox('Автоперемещение в бою')
        self.auto_move.setChecked(True)
        row.addWidget(self.auto_move)
        row.addWidget(QLabel('Крит:'))
        self.crit_mode = QComboBox()
        self.crit_mode.addItem('Удваивать весь урон', 'double_all')
        self.crit_mode.addItem('Удваивать только кости', 'dice_only')
        self.crit_mode.setCurrentIndex(0)
        row.addWidget(self.crit_mode)
        lay.addLayout(row)
        return page

    def rebuild_battle_lists(self):
        clear_layout(self.battle_lay)
        self.enemy_labels, self.side_checks = {}, []
        if not self.sides:
            hint = QLabel('Сначала создайте армии на вкладке «Настройка армий».')
            hint.setProperty('role', 'muted')
            self.battle_lay.addWidget(hint)
            self.battle_lay.addStretch()
            return
        cols = min(len(self.sides), 3)
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (side, name) in enumerate(zip(self.sides, self.side_names)):
            box = QGroupBox(name)
            bl = QVBoxLayout(box)
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setMinimumHeight(200)
            host = QWidget()
            hl = QVBoxLayout(host)
            hl.setContentsMargins(4, 4, 4, 4)
            all_cb = QCheckBox('Выделить все')
            hl.addWidget(all_cb)
            checks = []
            for e in side:
                e.attach(self.updater)
                r = QHBoxLayout()
                cb = QCheckBox()
                lab = QLabel(self._enemy_text(e))
                lab.mouseDoubleClickEvent = lambda ev, en=e: self.edit_one(en)
                r.addWidget(cb)
                r.addWidget(lab, 1)
                hl.addLayout(r)
                checks.append(cb)
                self.enemy_labels[e] = lab
            hl.addStretch()
            sa.setWidget(host)
            bl.addWidget(sa)
            all_cb.toggled.connect(lambda on, cs=checks: [c.setChecked(on) for c in cs])
            self.side_checks.append(checks)
            grid.addWidget(box, i // cols, i % cols)
        for c in range(cols):
            grid.setColumnStretch(c, 1)
        self.battle_lay.addLayout(grid)

    @staticmethod
    def _enemy_text(e):
        status = '🟢' if e.alive else '🔴'
        atk = ', '.join(f'{a.name}{"✦" if getattr(a, "magical", False) else ""}'
                        f'+{a.attack_bonus}' for a in e.attacks)
        return f'{status} {e.name}: {e.hp}/{e.max_hp} HP [{atk}]'

    def refresh_dirty(self):
        for e in list(self.dirty):
            lab = self.enemy_labels.get(e)
            if lab is not None:
                lab.setText(self._enemy_text(e))
        self.dirty.clear()

    def refresh_all_labels(self):
        for e, lab in self.enemy_labels.items():
            lab.setText(self._enemy_text(e))
        self.dirty.clear()

    def run_round(self):
        result = battle_round.run_round(
            self.sides, self.side_names, self.ignore_sides, self.battle_map,
            self.engine, auto_move=self.auto_move.isChecked(),
            crit_mode=self.crit_mode.currentData(), round_no=self.round_no + 1)
        outcome, text = result
        if outcome == 'empty':
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
        alive = sum(1 for s in self.sides for e in s if e.alive)
        attacks = sum(1 for event in result.events if event.kind == 'attack')
        self.status.showMessage(
            f'Раунд {self.round_no}: живых {alive}, атак {attacks}' +
            ('  ·  бой завершён' if outcome == 'over' else '') +
            '  ·  линии атак на карте')
        self._commit(f'раунд {self.round_no}')

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
        label = (f'правка: {enemies[0].name}' if len(enemies) == 1
                 else f'правка: {len(enemies)} существ')
        d = CreatureEditDialog(self, enemies)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all_labels()
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
            self.status.showMessage(f'Обновлено существ: {len(enemies)}')
            self._commit(label)

    def edit_one(self, enemy):
        label = f'правка: {enemy.name}'
        d = CreatureEditDialog(self, [enemy])
        if d.exec() == QDialog.DialogCode.Accepted:
            self.refresh_all_labels()
            self.map_view.rebuild(self.battle_map, self.sides, self.selected)
            self._commit(label)

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
        lay.addWidget(sa, 1)
        return page

    def refresh_alliances(self):
        clear_layout(self.all_grid)
        self.all_vars = []
        n = len(self.side_names)
        if n < 3:
            self.all_note.setText('Для настройки альянсов требуется минимум 3 стороны.')
            return
        self.all_note.setText('Отметьте, какие стороны игнорируют друг друга, '
                              'затем нажмите «Применить настройки альянсов» внизу.')
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

    def _build_map(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setSpacing(10)

        panel = QFrame()
        panel.setProperty('role', 'card')
        panel.setFixedWidth(296)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(12, 12, 12, 12)
        pv.setSpacing(8)
        head = QLabel('🎛 Отображение карты')
        head.setProperty('role', 'title')
        pv.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        pl = QVBoxLayout(body)
        pl.setContentsMargins(2, 2, 8, 2)
        pl.setSpacing(8)
        scroll.setWidget(body)
        pv.addWidget(scroll, 1)

        self._map_sliders = {}
        for key, label, lo, hi, suffix in (
                ('cell', 'Размер клетки', 16, 56, ' px'),
                ('zoom', 'Масштаб', 25, 300, ' %'),
                ('dead_alpha', 'Видимость павших', 10, 100, ' %'),
                ('stroke', 'Обводка токенов', 0, 4, ' px')):
            row, s, cap = self._slider(lo, hi, DEFAULT_OPTS[key], label, key, suffix)
            pl.addLayout(row)
            self._map_sliders[key] = (s, cap, label, suffix)

        self.cb_grid = QCheckBox('Сетка поля')
        self.cb_grid.setChecked(True)
        self.cb_grid.toggled.connect(lambda v: self.map_view.set_opt('grid', v))
        pl.addWidget(self.cb_grid)
        self.cb_reach = QCheckBox('Подсветка досягаемости')
        self.cb_reach.setChecked(True)
        self.cb_reach.toggled.connect(lambda v: self.map_view.set_opt('reach', v))
        pl.addWidget(self.cb_reach)
        self.cb_glow = QCheckBox('Свечение выбранного')
        self.cb_glow.setChecked(True)
        self.cb_glow.toggled.connect(lambda v: self.map_view.set_opt('glow', v))
        pl.addWidget(self.cb_glow)
        self.cb_attacks = QCheckBox('Линии атак')
        self.cb_attacks.setChecked(True)
        self.cb_attacks.setToolTip(
            'Последний раунд: красный — попадание, золотой — крит, '
            'серый пунктир — промах, фиолетовый — натуральная 1, зелёный — лечение')
        self.cb_attacks.toggled.connect(lambda v: self.map_view.set_opt('attack_lines', v))
        pl.addWidget(self.cb_attacks)

        pl.addWidget(QLabel('Подписи токенов:'))
        self.cmb_labels = QComboBox()
        self.cmb_labels.addItems(['Номер бойца', 'Имя стороны', 'Без подписей'])
        self.cmb_labels.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('labels', ['number', 'name', 'none'][i]))
        pl.addWidget(self.cmb_labels)

        pl.addWidget(QLabel('Палитра сторон:'))
        self.cmb_sides = QComboBox()
        self.cmb_sides.addItems(['Классическая', 'Неон', 'Пергамент'])
        self.cmb_sides.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('sides', ['classic', 'neon', 'parchment'][i]))
        pl.addWidget(self.cmb_sides)

        sep = QFrame()
        sep.setProperty('role', 'sep')
        sep.setFixedHeight(2)
        pl.addWidget(sep)

        bg_cap = QLabel('🖼 Фон карты')
        bg_cap.setProperty('role', 'accent')
        pl.addWidget(bg_cap)
        b_load = QPushButton('Загрузить изображение…')
        b_load.setCursor(Qt.CursorShape.PointingHandCursor)
        b_load.clicked.connect(self.load_map_background)
        pl.addWidget(b_load)
        self.bg_info = QLabel('Фон не задан. Можно перетащить картинку прямо на поле.')
        self.bg_info.setProperty('role', 'muted')
        self.bg_info.setWordWrap(True)
        pl.addWidget(self.bg_info)

        pl.addWidget(QLabel('Масштабирование фона:'))
        self.cmb_bg_mode = QComboBox()
        self.cmb_bg_mode.addItems(['Растянуть по карте', 'Вписать (с полями)',
                                   'Заполнить (обрезать)', 'Замостить'])
        self.cmb_bg_mode.currentIndexChanged.connect(
            lambda i: self.map_view.set_opt('bg_mode', BG_MODES[i]))
        pl.addWidget(self.cmb_bg_mode)

        row, s, cap = self._slider(10, 100, DEFAULT_OPTS['bg_opacity'],
                                   'Непрозрачность фона', 'bg_opacity', ' %')
        pl.addLayout(row)
        self._map_sliders['bg_opacity'] = (s, cap, 'Непрозрачность фона', ' %')

        b_clear = QPushButton('✕ Убрать фон')
        b_clear.setProperty('variant', 'danger')
        b_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        b_clear.clicked.connect(self.clear_map_background)
        pl.addWidget(b_clear)
        pl.addStretch()

        for text, fn, variant in (('↺ Сбросить вид', self.reset_map_opts, 'outline'),
                                  ('🎲 Случайный вид', self.randomize_map_opts, 'outline'),
                                  ('🖼 Экспорт PNG', self.export_map_png, 'primary')):
            b = QPushButton(text)
            b.setProperty('variant', variant)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            pv.addWidget(b)
        outer.addWidget(panel)

        right = QVBoxLayout()
        hint = QLabel('Колесо — зум · тяни поле — панорама · клик по токену — выбрать · '
                      'перетащи токен или кликни по зелёной клетке — ход · Ctrl+Z — отмена · '
                      'картинку можно бросить на поле мышью')
        hint.setProperty('role', 'muted')
        right.addWidget(hint)
        split = QSplitter(Qt.Orientation.Vertical)
        self.map_view = MapView(self.theme.palette())
        self.map_view.token_clicked.connect(self.on_token)
        self.map_view.cell_clicked.connect(self.on_cell)
        self.map_view.token_dragged.connect(self.on_token_dragged)
        self.map_view.image_dropped.connect(self._apply_background_path)
        split.addWidget(self.map_view)
        mirror = QWidget()
        mirror_lay = QVBoxLayout(mirror)
        mirror_lay.setContentsMargins(0, 0, 0, 0)
        self.log_panel.attach_mirror(mirror_lay)
        split.addWidget(mirror)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([520, 200])
        right.addWidget(split, 1)
        self.map_info = QLabel('Токен не выбран.')
        self.map_info.setProperty('role', 'muted')
        right.addWidget(self.map_info)
        outer.addLayout(right, 1)
        self._sync_bg_info()
        return page

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

    def on_token(self, enemy):
        self.selected = enemy
        self.map_view.rebuild(self.battle_map, self.sides, self.selected)
        pos = self.battle_map.get_pos(enemy)
        left = enemy.speed - getattr(enemy, 'moved_ft', 0)
        self.map_info.setText(f'{enemy.name}: HP {enemy.hp}/{enemy.max_hp}, AC {enemy.ac}, '
                              f'клетка {pos}, скорость {enemy.speed} фт, остаток {left} фт')
        self._note_selection()

    def on_token_dragged(self, enemy, x, y):
        if enemy is None:
            return
        self.selected = enemy
        self._note_selection()
        self.on_cell(x, y)

    def on_cell(self, x, y):
        if self.battle_map is None or self.selected is None or not self.selected.alive:
            return
        pos = self.battle_map.get_pos(self.selected)
        if not pos:
            return
        dist = max(abs(x - pos[0]), abs(y - pos[1])) * 5
        if dist == 0:
            return
        left = self.selected.speed - getattr(self.selected, 'moved_ft', 0)
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
                'map_opts': dict(self.map_view.opts),
                'map_bg': self.map_view.background_path,
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