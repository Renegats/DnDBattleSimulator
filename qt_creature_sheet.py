"""Карточка существа и диалог «добавить на клетку».

Карточка немодальная: карта остаётся на виду, секции сворачиваются.
Поля те же, что были в редакторе существа и на карточке отряда:
имя, сторона, тактика, хиты, КД, скорость, инициатива, атаки,
характеристики, состояния. Особые действия статблока показаны текстом —
их сценарий боя карточка не переписывает.
"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
                             QCheckBox, QMessageBox, QScrollArea, QFrame, QPlainTextEdit)

from qt_editors import (Section, AttackListEditor, CharacteristicsEditor, CHAR_KEYS,
                        STRATS, attack_dict, strategy_name, make_strategy, SideCreatorDialog)

NEW_SIDE = 'Новая сторона…'


def _spin(lo, hi, value, name=None):
    box = QSpinBox()
    box.setRange(lo, hi)
    box.setValue(int(value))
    box.setFixedWidth(72)
    if name:
        box.setObjectName(name)
    return box


def _stat(title, inner):
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(1)
    cap = QLabel(title)
    cap.setProperty('role', 'muted')
    cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(cap)
    lay.addWidget(inner, 0, Qt.AlignmentFlag.AlignHCenter)
    return host


def _rule():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setProperty('role', 'sep')
    line.setFixedHeight(2)
    return line


def action_lines(enemy):
    """Имена особых действий. Сценарии (урон, спасброски) карточка не редактирует."""
    rows = []
    for title, attr in (('Действие', 'special_actions'),
                        ('Бонусное', 'bonus_actions'),
                        ('Реакция', 'reactions')):
        for item in getattr(enemy, attr, None) or []:
            if isinstance(item, dict):
                name = item.get('name') or 'действие'
            else:
                name = str(item)
            rows.append(f'{title}: {name}')
    legendary = getattr(enemy, 'legendary_actions', None) or {}
    options = legendary.get('options') if isinstance(legendary, dict) else None
    for item in options or []:
        if isinstance(item, dict):
            name = item.get('name') or 'легендарное'
        else:
            name = str(item)
        rows.append(f'Легендарное: {name}')
    return rows


class CreatureSheet(QDialog):
    """Немодальная карточка. `applied` — пользователь нажал «Применить»."""

    applied = pyqtSignal()

    def __init__(self, parent, enemies, side_names):
        super().__init__(parent)
        self.enemies = list(enemies)
        self.setObjectName('creature_sheet')
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Window, True)
        e0 = self.enemies[0]
        title = e0.name if len(self.enemies) == 1 else f'{len(self.enemies)} существ'
        self.setWindowTitle(f'Карточка — {title}')
        self.resize(460, 720)
        self.setMinimumWidth(400)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        if len(self.enemies) > 1:
            note = QLabel(f'Правки применятся ко всем выбранным: {len(self.enemies)}')
            note.setProperty('role', 'muted')
            note.setWordWrap(True)
            outer.addWidget(note)

        self.name = QLineEdit(e0.name)
        self.name.setObjectName('sheet_name')
        self.name.setProperty('role', 'title')
        outer.addWidget(self.name)

        side_row = QHBoxLayout()
        side_row.setSpacing(8)
        self.side = QComboBox()
        self.side.setObjectName('sheet_side')
        for label in side_names:
            self.side.addItem(label)
        self.side.addItem(NEW_SIDE)
        current = int(getattr(e0, 'side', 0) or 0)
        if 0 <= current < len(side_names):
            self.side.setCurrentIndex(current)
        else:
            self.side.setCurrentIndex(self.side.count() - 1)
        self.tactic = QComboBox()
        self.tactic.setObjectName('sheet_tactic')
        self.tactic.addItems(STRATS)
        self.tactic.setCurrentText(strategy_name(getattr(e0, 'strategy', None)))
        side_row.addWidget(self.side, 1)
        side_row.addWidget(self.tactic, 1)
        outer.addLayout(side_row)

        vitals = QHBoxLayout()
        vitals.setSpacing(10)
        hp_host = QWidget()
        hp_lay = QHBoxLayout(hp_host)
        hp_lay.setContentsMargins(0, 0, 0, 0)
        hp_lay.setSpacing(4)
        self.hp = _spin(0, 2000, e0.hp, 'sheet_hp')
        self.max_hp = _spin(1, 2000, e0.max_hp, 'sheet_max_hp')
        slash = QLabel('/')
        slash.setProperty('role', 'muted')
        hp_lay.addWidget(self.hp)
        hp_lay.addWidget(slash)
        hp_lay.addWidget(self.max_hp)
        vitals.addWidget(_stat('Хиты', hp_host))
        self.ac = _spin(1, 40, e0.ac, 'sheet_ac')
        vitals.addWidget(_stat('КД', self.ac))
        self.speed = _spin(0, 300, getattr(e0, 'speed', 30), 'sheet_speed')
        vitals.addWidget(_stat('Скорость', self.speed))
        self.regen = _spin(0, 200, getattr(e0, 'regen', 0), 'sheet_regen')
        vitals.addWidget(_stat('Реген.', self.regen))
        self.initiative = _spin(-10, 20, int(getattr(e0, 'initiative_bonus', 0) or 0),
                                'sheet_init')
        vitals.addWidget(_stat('Бонус иниц.', self.initiative))
        vitals.addStretch()
        outer.addLayout(vitals)

        self.init_hint = QLabel('')
        self.init_hint.setProperty('role', 'muted')
        self.init_hint.setWordWrap(True)
        outer.addWidget(self.init_hint)
        outer.addWidget(_rule())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 2, 8, 2)
        lay.setSpacing(6)

        attacks = Section('Атаки')
        self._sec_attacks = attacks
        attacks.body_lay.addWidget(QLabel('Двойной щелчок по строке меняет атаку.'))
        self.atk = AttackListEditor(attacks, [attack_dict(a) for a in e0.attacks])
        attacks.body_lay.addWidget(self.atk)
        lines = action_lines(e0)
        if lines:
            extra = QPlainTextEdit('\n'.join(lines))
            extra.setReadOnly(True)
            extra.setFixedHeight(min(120, 22 * len(lines) + 12))
            extra.setToolTip('Сценарий этих действий карточка не меняет: '
                             'он остаётся у существа, как пришёл из статблока.')
            attacks.body_lay.addWidget(QLabel('Прочие действия статблока (только просмотр):'))
            attacks.body_lay.addWidget(extra)
        attacks.arrow.setChecked(True)
        lay.addWidget(attacks)

        self.chars = CharacteristicsEditor(
            initial={k: getattr(e0, k, None) for k in CHAR_KEYS})
        lay.addWidget(self.chars)

        cond = Section('Состояния')
        self._sec_conditions = cond
        from conditions import MANUAL_IDS, active_conditions, condition_name, exhaustion_level
        grid = QGridLayout()
        present = {item.get('id') for item in active_conditions(e0) if isinstance(item, dict)}
        self.cond_boxes = {}
        for index, condition_id in enumerate(MANUAL_IDS):
            box = QCheckBox(condition_name(condition_id))
            box.setChecked(condition_id in present)
            self.cond_boxes[condition_id] = box
            grid.addWidget(box, index // 2, index % 2)
        cond.body_lay.addLayout(grid)
        exh = QHBoxLayout()
        exh.addWidget(QLabel('Истощение (0–6):'))
        self.exhaustion = QSpinBox()
        self.exhaustion.setObjectName('sheet_exhaustion')
        self.exhaustion.setRange(0, 6)
        self.exhaustion.setValue(exhaustion_level(e0))
        exh.addWidget(self.exhaustion)
        exh.addStretch()
        cond.body_lay.addLayout(exh)
        cond.arrow.setChecked(True)
        lay.addWidget(cond)
        lay.addStretch()
        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        row = QHBoxLayout()
        close = QPushButton('Закрыть')
        close.setProperty('variant', 'outline')
        close.clicked.connect(self.close)
        apply = QPushButton('Применить')
        apply.setObjectName('sheet_apply')
        apply.setProperty('variant', 'primary')
        apply.setDefault(True)
        apply.clicked.connect(self.apply_changes)
        row.addWidget(close)
        row.addStretch()
        row.addWidget(apply)
        outer.addLayout(row)

        self.initiative.valueChanged.connect(lambda _v: self._refresh_init_hint())
        dex = self.chars.entries.get('mod_dex')
        if dex is not None:
            dex.textChanged.connect(lambda _t: self._refresh_init_hint())
        self._refresh_init_hint()

    def chosen_side(self):
        """Индекс стороны или -1, если выбрана «Новая сторона»."""
        if self.side.currentText() == NEW_SIDE:
            return -1
        return self.side.currentIndex()

    def _dex_mod(self):
        data = self.chars.get_data()
        raw = (data.get('ability_mods') or {}).get('dex')
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _refresh_init_hint(self):
        dex = self._dex_mod()
        bonus = self.initiative.value()
        total = dex + bonus
        sign = f'+{total}' if total >= 0 else str(total)
        dex_sign = f'+{dex}' if dex >= 0 else str(dex)
        bonus_sign = f'+{bonus}' if bonus >= 0 else str(bonus)
        self.init_hint.setText(
            f'Инициатива: d20 {sign}  ·  Ловкость {dex_sign}, бонус {bonus_sign}. '
            'Без бонуса бросок как раньше: только кость и Ловкость.')

    def apply_changes(self):
        if not self.atk.attacks:
            QMessageBox.warning(self, 'Внимание', 'Нужна хотя бы одна атака!')
            return False
        self.applied.emit()
        return True

    def write_creatures(self):
        """Пишет поля в существ. Сторону между списками перекладывает окно."""
        from entities import Attack
        from conditions import clear_conditions, sync_manual_conditions
        chars = self.chars.get_data()
        marked = [cid for cid, box in self.cond_boxes.items() if box.isChecked()]
        for enemy in self.enemies:
            enemy.name = self.name.text().strip() or enemy.name
            enemy.max_hp = self.max_hp.value()
            enemy.hp = min(self.hp.value(), enemy.max_hp)
            enemy.ac = self.ac.value()
            enemy.speed = self.speed.value()
            enemy.regen = self.regen.value()
            enemy.initiative_bonus = self.initiative.value()
            enemy.alive = enemy.hp > 0
            enemy.strategy = make_strategy(self.tactic.currentText())
            previous = {attack.name: attack for attack in enemy.attacks}
            built = []
            for raw in self.atk.attacks:
                old = previous.get(raw['name'])
                extra = raw.get('extra_damage')
                riders = raw.get('riders')
                if extra is None and old is not None:
                    extra = getattr(old, 'extra_damage', None)
                if riders is None and old is not None:
                    riders = getattr(old, 'riders', None)
                built.append(Attack(
                    raw['name'], raw['attack_bonus'], raw['damage_dice_count'],
                    raw['damage_dice_type'], raw['damage_modifier'],
                    raw.get('damage_type', ''), raw.get('range_ft', 5),
                    raw.get('magical', False), extra, riders))
            enemy.attacks = built
            for key, value in chars.items():
                setattr(enemy, key, value)
            sync_manual_conditions(enemy, marked, self.exhaustion.value())
            if enemy.hp <= 0 or not enemy.alive:
                enemy.hp = 0
                enemy.alive = False
                clear_conditions(enemy)


class AddCreatureDialog(QDialog):
    """Одно существо: пресет, бестиарий или свой статблок, затем клетка карты."""

    def __init__(self, parent, types, side_labels, cell=None, current_type=None):
        super().__init__(parent)
        self.setObjectName('add_creature_dialog')
        self.setWindowTitle('Добавить существо сюда' if cell else 'Добавить существо')
        self.resize(440, 280)
        self._types = list(types)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        if cell is not None:
            where = QLabel(f'Клетка {cell[0]:g}, {cell[1]:g}. Если занята — ближайшая свободная.')
        else:
            where = QLabel('Существо встанет на ближайшую свободную клетку своей стороны.')
        where.setProperty('role', 'muted')
        where.setWordWrap(True)
        lay.addWidget(where)

        self.name = QLineEdit(current_type or (self._types[0] if self._types else ''))
        self.name.setObjectName('add_name')
        lay.addWidget(QLabel('Имя'))
        lay.addWidget(self.name)

        self.kind = QComboBox()
        self.kind.setObjectName('add_type')
        self.kind.addItems(self._types)
        if current_type and current_type in self._types:
            self.kind.setCurrentText(current_type)
            self.name.setText(current_type)
        self.kind.currentTextChanged.connect(self._on_type)
        lay.addWidget(QLabel('Состав'))
        lay.addWidget(self.kind)

        self.side = QComboBox()
        self.side.setObjectName('add_side')
        for label in side_labels:
            self.side.addItem(label)
        self.side.addItem(NEW_SIDE)
        lay.addWidget(QLabel('Сторона'))
        lay.addWidget(self.side)

        self.tactic = QComboBox()
        self.tactic.setObjectName('add_tactic')
        self.tactic.addItems(STRATS)
        lay.addWidget(QLabel('Тактика'))
        lay.addWidget(self.tactic)

        tools = QHBoxLayout()
        bestiary = QPushButton('Из бестиария…')
        bestiary.setProperty('variant', 'outline')
        bestiary.clicked.connect(self._import)
        custom = QPushButton('Своё существо…')
        custom.setProperty('variant', 'outline')
        custom.clicked.connect(self._custom)
        tools.addWidget(bestiary)
        tools.addWidget(custom)
        tools.addStretch()
        lay.addLayout(tools)

        row = QHBoxLayout()
        cancel = QPushButton('Отмена')
        cancel.setProperty('variant', 'outline')
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Добавить')
        ok.setObjectName('add_accept')
        ok.setProperty('variant', 'primary')
        ok.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def _on_type(self, text):
        if not self.name.text().strip() or self.name.text().strip() in self._types:
            self.name.setText(text)

    def _remember(self, type_name):
        if not type_name:
            return
        if type_name not in self._types:
            self._types.append(type_name)
            self.kind.addItem(type_name)
        self.kind.setCurrentText(type_name)
        self.name.setText(type_name)

    def _import(self):
        from qt_bestiary import BestiaryDialog
        dialog = BestiaryDialog(self)
        dialog.imported.connect(self._remember)
        dialog.exec()

    def _custom(self):
        dialog = SideCreatorDialog(self, self._types, mode='spawn')
        dialog.stack.setCurrentIndex(1)
        dialog.ready.connect(lambda res: self._remember(res.get('army_type')))
        dialog.exec()

    def result_data(self):
        side = -1 if self.side.currentText() == NEW_SIDE else self.side.currentIndex()
        return {
            'name': self.name.text().strip(),
            'type': self.kind.currentText(),
            'side': side,
            'strategy': self.tactic.currentText(),
        }
