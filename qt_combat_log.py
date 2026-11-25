"""Панель журнала боя: модель + фильтр, без пересборки текста каждый раунд.

Дерево «раунд → события» дописывается пачкой (beginInsertRows). Фильтр — прокси,
поэтому поиск и отбор по стороне / существу / типу не пересоздают строки.
"""
from PyQt6.QtCore import Qt, QModelIndex, QAbstractItemModel, QSortFilterProxyModel, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QLabel,
                             QLineEdit, QTreeView, QVBoxLayout, QWidget)

from combat_log import event_visible

KIND_FILTERS = (
    ('all', 'Все события'),
    ('hit', 'Попадания'),
    ('crit', 'Криты'),
    ('miss', 'Промахи'),
    ('nat1', 'Натуральные 1'),
    ('death', 'Убийства'),
    ('heal', 'Лечение'),
    ('move', 'Движение'),
    ('legendary', 'Легендарные'),
    ('initiative', 'Инициатива'),
)


def display_text(event) -> str:
    compact = ' '.join((event.text or '').split())
    if event.result == 'nat1' and 'натуральн' not in compact.casefold():
        compact = f'{compact} · натуральная 1' if compact else 'натуральная 1'
    return compact


def color_of(event):
    if event.result == 'crit':
        return '#d4a017'
    if event.result == 'nat1':
        return '#8e44ad'
    if event.kind == 'death' or event.result == 'death':
        return '#c0392b'
    if event.result == 'hit':
        return '#d35400'
    if event.result == 'miss':
        return '#7f8c8d'
    if event.kind == 'heal' or event.result == 'heal':
        return '#1e8449'
    if event.legendary or event.kind == 'legendary':
        return '#6c3483'
    if event.kind == 'move':
        return '#2471a3'
    if event.kind in ('round_start', 'initiative', 'round_end'):
        return '#3d4db7'
    if event.result == 'victory':
        return '#d4a017'
    return None


def tooltip_of(event) -> str:
    from combat_log import detail_lines
    parts = []
    raw = (event.text or '').strip()
    if raw:
        parts.append(raw)
    parts.extend(detail_lines(event))
    return '\n'.join(parts)


class _Node:
    def __init__(self, parent=None):
        self.parent = parent
        self.children = []
        self.event = None
        self.title = ''
        self.color = None
        self.bold = False
        self.tip = ''


class CombatLogModel(QAbstractItemModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = _Node()

    def index(self, row, column, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self.root
        if row < 0 or column != 0 or row >= len(node.children):
            return QModelIndex()
        return self.createIndex(row, column, node.children[row])

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        node = index.internalPointer()
        if node is None or node.parent is None or node.parent is self.root:
            return QModelIndex()
        grand = node.parent.parent
        row = grand.children.index(node.parent)
        return self.createIndex(row, 0, node.parent)

    def rowCount(self, parent=QModelIndex()):
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return 1

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node = index.internalPointer()
        if role == Qt.ItemDataRole.DisplayRole:
            return node.title
        if role == Qt.ItemDataRole.UserRole:
            return node.event
        if role == Qt.ItemDataRole.ForegroundRole and node.color:
            return QBrush(QColor(node.color))
        if role == Qt.ItemDataRole.ToolTipRole and node.tip:
            return node.tip
        if role == Qt.ItemDataRole.FontRole and node.bold:
            font = QFont()
            font.setBold(True)
            return font
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def clear(self):
        self.beginResetModel()
        self.root = _Node()
        self.endResetModel()

    def append_group(self, title, events, color='#3d4db7'):
        rows = [event for event in events
                if event is not None and event.kind != 'spacer' and event.text]
        if not rows:
            return
        parent_row = len(self.root.children)
        self.beginInsertRows(QModelIndex(), parent_row, parent_row)
        node = _Node(self.root)
        node.title = title
        node.bold = True
        node.color = color
        for event in rows:
            child = self._leaf(node, event)
            node.children.append(child)
        self.root.children.append(node)
        self.endInsertRows()

    def append_round(self, events):
        number = next((event.round for event in events if getattr(event, 'round', None)), None)
        title = f'Раунд {number}' if number else 'Раунд'
        self.append_group(title, events)

    def append_notes(self, events):
        rows = [event for event in events if event is not None and event.text]
        if not rows:
            return
        first = len(self.root.children)
        self.beginInsertRows(QModelIndex(), first, first + len(rows) - 1)
        for event in rows:
            self.root.children.append(self._leaf(self.root, event))
        self.endInsertRows()

    @staticmethod
    def _leaf(parent, event):
        node = _Node(parent)
        node.event = event
        node.title = display_text(event)
        node.color = color_of(event)
        node.bold = event.result == 'crit' or event.kind == 'death'
        node.tip = tooltip_of(event)
        return node


class LogFilterProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.side = None
        self.creature_id = None
        self.kind = 'all'
        self.query = ''

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        index = model.index(source_row, 0, source_parent)
        if self._row_ok(index):
            return True
        # Заголовок раунда остаётся, если под ним есть хоть одна подходящая строка.
        for row in range(model.rowCount(index)):
            if self.filterAcceptsRow(row, index):
                return True
        return False

    def _row_ok(self, index):
        event = index.data(Qt.ItemDataRole.UserRole)
        return event_visible(
            event, side=self.side, creature_id=self.creature_id,
            kind=self.kind, query=self.query)


class CombatLogPanel(QWidget):
    entry_activated = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._views = []
        self._quiet = False
        self.model = CombatLogModel(self)
        self.proxy = LogFilterProxy(self)
        self.proxy.setSourceModel(self.model)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        cap = QLabel('Журнал боя')
        cap.setProperty('role', 'title')
        lay.addWidget(cap)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self.side = QComboBox()
        self.creature = QComboBox()
        self.kind = QComboBox()
        for box in (self.side, self.creature, self.kind):
            box.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            box.setMinimumContentsLength(12)
        self.kind.setMaximumWidth(190)
        self.side.setMaximumWidth(180)
        for key, label in KIND_FILTERS:
            self.kind.addItem(label, key)
        self.search = QLineEdit()
        self.search.setPlaceholderText('Поиск по журналу')
        self.search.setClearButtonEnabled(True)
        filters.addWidget(self.side)
        filters.addWidget(self.creature)
        filters.addWidget(self.kind)
        filters.addWidget(self.search, 1)
        lay.addLayout(filters)

        self.view = self._make_view()
        lay.addWidget(self.view, 1)
        self.set_roster([], [])

        self.side.currentIndexChanged.connect(self._push_filter)
        self.creature.currentIndexChanged.connect(self._push_filter)
        self.kind.currentIndexChanged.connect(self._push_filter)
        self.search.textChanged.connect(self._push_filter)

    def _make_view(self):
        view = QTreeView()
        view.setModel(self.proxy)
        view.setHeaderHidden(True)
        view.setUniformRowHeights(True)
        view.setAnimated(False)
        view.setIndentation(14)
        view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        font = QFont('DejaVu Sans Mono', 9)
        font.setStyleHint(QFont.StyleHint.Monospace)
        view.setFont(font)
        view.setStyleSheet(
            'QTreeView::item:selected { background: #5865f2; color: #ffffff; }')
        self._views.append(view)
        view.selectionModel().currentChanged.connect(self._activate_current)
        return view

    def attach_mirror(self, layout):
        """Второе дерево на той же модели: клики на карте не пересобирают журнал."""
        note = QLabel('Журнал боя — клик центрирует токены. '
                      'Фильтры те же, что на вкладке «Битва».')
        note.setProperty('role', 'muted')
        note.setWordWrap(True)
        layout.addWidget(note)
        view = self._make_view()
        layout.addWidget(view, 1)
        return view

    def set_roster(self, sides, side_names):
        self._quiet = True
        self.side.blockSignals(True)
        self.creature.blockSignals(True)
        self.side.clear()
        self.side.addItem('Все стороны', None)
        for index, name in enumerate(side_names):
            self.side.addItem(name, index)
        self.creature.clear()
        self.creature.addItem('Все существа', None)
        for side in sides or []:
            for enemy in side:
                self.creature.addItem(enemy.name, id(enemy))
        self.side.setCurrentIndex(0)
        self.creature.setCurrentIndex(0)
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(0)
        self.kind.blockSignals(False)
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self.side.blockSignals(False)
        self.creature.blockSignals(False)
        self.proxy.side = None
        self.proxy.creature_id = None
        self.proxy.kind = 'all'
        self.proxy.query = ''
        self.proxy.invalidate()
        self._quiet = False

    def set_kind(self, key):
        index = self.kind.findData(key)
        if index >= 0:
            self.kind.setCurrentIndex(index)

    def set_search(self, text):
        self.search.setText(text)

    def _push_filter(self, *_args):
        if self._quiet:
            return
        self.proxy.side = _as_int(self.side.currentData())
        self.proxy.creature_id = _as_int(self.creature.currentData())
        self.proxy.kind = self.kind.currentData() or 'all'
        self.proxy.query = self.search.text()
        self._quiet = True
        self.proxy.invalidate()
        for view in self._views:
            view.expandAll()
        self._quiet = False

    def append_round(self, events):
        self.model.append_round(events)
        self._reveal_last()

    def add_note(self, text):
        from combat_log import CombatEvent
        events = []
        for line in str(text).splitlines():
            if line.strip():
                events.append(CombatEvent(kind='note', text=line))
        self.model.append_notes(events)
        self._reveal_last()
        return events

    def clear(self):
        self.model.clear()

    def _reveal_last(self):
        if self.model.rowCount() == 0:
            return
        source = self.model.index(self.model.rowCount() - 1, 0)
        proxy_index = self.proxy.mapFromSource(source)
        for view in self._views:
            if self.model.rowCount(source):
                view.expand(proxy_index)
            view.scrollTo(proxy_index, QAbstractItemView.ScrollHint.PositionAtBottom)

    def _activate_current(self, current, _previous):
        if self._quiet or not current.isValid():
            return
        event = current.data(Qt.ItemDataRole.UserRole)
        if event is not None:
            self.entry_activated.emit(event)

    def visible_events(self):
        found = []

        def walk(parent):
            for row in range(self.proxy.rowCount(parent)):
                index = self.proxy.index(row, 0, parent)
                event = index.data(Qt.ItemDataRole.UserRole)
                if event is not None:
                    found.append(event)
                walk(index)

        walk(QModelIndex())
        return found


def _as_int(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
