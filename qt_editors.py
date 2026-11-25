"""Qt-редакторы: атака (с флагом магичности), характеристики, существо, создатель стороны."""
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
                             QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
                             QListWidget, QPlainTextEdit, QToolButton, QScrollArea,
                             QCheckBox, QMessageBox, QStackedWidget)

from factory import EnemyFactory

ABILITY_ROWS = [('str', 'СИЛ'), ('dex', 'ЛОВ'), ('con', 'ТЕЛ'),
                ('int', 'ИНТ'), ('wis', 'МДР'), ('cha', 'ХАР')]
DICT_FIELDS = [('saves', 'Спасброски'), ('skills', 'Навыки'), ('senses', 'Чувства')]
LIST_FIELDS = [('vulnerabilities', 'Уязвимости к урону'),
               ('resistances', 'Сопротивления урону'),
               ('immunities', 'Иммунитеты к урону'),
               ('condition_immunities', 'Иммунитеты к условиям'),
               ('languages', 'Языки')]
SCALAR_FIELDS = [('cr', 'Опасность (CR)'), ('prof_bonus', 'Бонус мастерства'),
                 ('size', 'Размер'), ('type', 'Тип')]
DICE = ['d4', 'd6', 'd8', 'd10', 'd12', 'd20']
STRATS = ['случайная', 'агрессивная', 'защитная', 'поддержка']
CHAR_KEYS = ('ability_scores', 'ability_mods', 'saves', 'skills', 'senses',
             'vulnerabilities', 'resistances', 'immunities', 'condition_immunities',
             'languages', 'cr', 'prof_bonus', 'size', 'type', 'traits')


def _int(s):
    s = (s or '').strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_pairs(seg):
    res = {}
    for part in [p.strip() for p in seg.replace('\n', ',').split(',') if p.strip()]:
        m = re.match(r'^(.+?)\s*[:\s]\s*([+-]?\d+)$', part)
        if m:
            res[m.group(1).strip()] = m.group(2)
        elif ' ' in part:
            k, v = part.rsplit(' ', 1)
            res[k.strip()] = v.strip()
    return res


def parse_list(seg):
    return [p.strip() for p in seg.replace('\n', ',').split(',') if p.strip()]


def parse_traits(seg):
    out = []
    for line in seg.split('\n'):
        line = line.strip()
        if not line:
            continue
        m = re.match(r'^([^.!?:]{1,60}?)\.\s+(.*)$', line)
        if m:
            out.append({'name': m.group(1).strip(' *'), 'desc': m.group(2).strip()})
        else:
            out.append({'name': line, 'desc': ''})
    return out


def attack_line(a):
    mark = ' ✦маг.' if a.get('magical') else ''
    return (f"{a['name']}{mark} ({a['attack_bonus']:+d}, {a['damage_dice_count']}"
            f"{a['damage_dice_type']}{a['damage_modifier']:+d}) "
            f"{a.get('damage_type') or '—'} · {a.get('range_ft', 5)} фт")


def attack_dict(a):
    data = {'name': a.name, 'attack_bonus': a.attack_bonus,
            'damage_dice_count': a.damage_dice_count,
            'damage_dice_type': a.damage_dice_type,
            'damage_modifier': a.damage_modifier,
            'damage_type': getattr(a, 'damage_type', ''),
            'range_ft': getattr(a, 'range_ft', 5),
            'magical': bool(getattr(a, 'magical', False))}
    extra = getattr(a, 'extra_damage', None)
    if extra:
        data['extra_damage'] = [dict(part) for part in extra]
    return data


class Section(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(2)
        head = QHBoxLayout()
        self.arrow = QToolButton()
        self.arrow.setCheckable(True)
        self.arrow.setArrowType(Qt.ArrowType.RightArrow)
        cap = QToolButton()
        cap.setText(title)
        cap.setCheckable(True)
        cap.setStyleSheet('font-weight: bold; font-size: 11pt;')
        cap.toggled.connect(self.arrow.setChecked)
        self.arrow.toggled.connect(cap.setChecked)
        self.arrow.toggled.connect(self._toggle)
        head.addWidget(self.arrow)
        head.addWidget(cap)
        head.addStretch()
        lay.addLayout(head)
        self.body = QWidget()
        self.body.setVisible(False)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(18, 0, 0, 4)
        lay.addWidget(self.body)

    def _toggle(self, on):
        self.arrow.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.body.setVisible(on)


class AttackDialog(QDialog):
    def __init__(self, parent=None, init=None):
        super().__init__(parent)
        self.setWindowTitle('Атака')
        self.resize(400, 470)
        init = dict(init or {'name': 'Атака', 'attack_bonus': 0, 'damage_dice_count': 1,
                             'damage_dice_type': 'd6', 'damage_modifier': 0,
                             'damage_type': '', 'range_ft': 5, 'magical': False})
        self._kept_extra = list(init.get('extra_damage') or [])
        lay = QVBoxLayout(self)
        self.name = QLineEdit(init['name'])
        self.dtype = QLineEdit(init.get('damage_type', ''))
        lay.addWidget(QLabel('Название'))
        lay.addWidget(self.name)
        lay.addWidget(QLabel('Тип урона'))
        lay.addWidget(self.dtype)
        self.spins = {}
        for key, lab, lo, hi in (('attack_bonus', 'Бонус к попаданию', -10, 30),
                                 ('damage_dice_count', 'Кол-во костей', 1, 20),
                                 ('damage_modifier', 'Модификатор урона', -20, 50),
                                 ('range_ft', 'Дальность (фт)', 5, 600)):
            lay.addWidget(QLabel(lab))
            s = QSpinBox()
            s.setRange(lo, hi)
            s.setValue(int(init.get(key, 0)))
            self.spins[key] = s
            lay.addWidget(s)
        lay.addWidget(QLabel('Тип кости'))
        self.dice = QComboBox()
        self.dice.addItems(DICE)
        self.dice.setCurrentText(init.get('damage_dice_type', 'd6'))
        lay.addWidget(self.dice)
        self.magical = QCheckBox('✦ Магическое оружие (пробивает иммунитет к немагическому)')
        self.magical.setChecked(bool(init.get('magical', False)))
        lay.addWidget(self.magical)
        lay.addStretch()
        row = QHBoxLayout()
        cancel = QPushButton('Отмена')
        cancel.setProperty('variant', 'outline')
        cancel.clicked.connect(self.reject)
        ok = QPushButton('Сохранить')
        ok.setProperty('variant', 'primary')
        ok.clicked.connect(self.accept)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(ok)
        lay.addLayout(row)

    def data(self):
        d = {'name': self.name.text().strip() or 'Атака',
             'damage_type': self.dtype.text().strip(),
             'damage_dice_type': self.dice.currentText(),
             'magical': self.magical.isChecked()}
        d.update({k: s.value() for k, s in self.spins.items()})
        if self._kept_extra:
            d['extra_damage'] = self._kept_extra
        return d


class CharacteristicsEditor(QWidget):
    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.entries, self.texts = {}, {}

        stats = Section('📊 Характеристики')
        lay.addWidget(stats)
        grid = QGridLayout()
        for r, (key, label) in enumerate(ABILITY_ROWS):
            lab = QLabel(label)
            lab.setProperty('role', 'accent')
            grid.addWidget(lab, r, 0)
            sc, md = QLineEdit(), QLineEdit()
            sc.setFixedWidth(56)
            md.setFixedWidth(56)
            grid.addWidget(sc, r, 1)
            grid.addWidget(QLabel('('), r, 2)
            grid.addWidget(md, r, 3)
            grid.addWidget(QLabel(')'), r, 4)
            self.entries['score_' + key] = sc
            self.entries['mod_' + key] = md
        grid.setColumnStretch(5, 1)
        stats.body_lay.addLayout(grid)
        for key, label in DICT_FIELDS:
            stats.body_lay.addWidget(QLabel(label + ':'))
            t = QPlainTextEdit()
            t.setFixedHeight(46)
            t.setPlaceholderText('Сил +3, Лов +2')
            self.texts[key] = t
            stats.body_lay.addWidget(t)

        df = Section('🛡 Особенности и защита')
        lay.addWidget(df)
        sg = QGridLayout()
        for i, (key, label) in enumerate(SCALAR_FIELDS):
            sg.addWidget(QLabel(label + ':'), i // 2, (i % 2) * 2)
            e = QLineEdit()
            e.setFixedWidth(120)
            self.entries[key] = e
            sg.addWidget(e, i // 2, (i % 2) * 2 + 1)
        sg.setColumnStretch(4, 1)
        df.body_lay.addLayout(sg)
        for key, label in LIST_FIELDS:
            df.body_lay.addWidget(QLabel(label + ':'))
            t = QPlainTextEdit()
            t.setFixedHeight(34)
            t.setPlaceholderText('огонь, холод  ·  либо: дробящий от немагического оружия')
            self.texts[key] = t
            df.body_lay.addWidget(t)
        df.body_lay.addWidget(QLabel('Особенности (Имя. Описание — по строкам):'))
        t = QPlainTextEdit()
        t.setFixedHeight(90)
        t.setPlaceholderText('Магическое оружие. Атаки оружием считаются магическими.')
        self.texts['traits'] = t
        df.body_lay.addWidget(t)
        self.set_data(initial or {})

    def set_data(self, d):
        sc, md = d.get('ability_scores') or {}, d.get('ability_mods') or {}
        for key, _ in ABILITY_ROWS:
            self.entries['score_' + key].setText('' if key not in sc else str(sc[key]))
            v = md.get(key)
            self.entries['mod_' + key].setText('' if v is None else
                                               (f'+{v}' if v >= 0 else str(v)))
        for key, _ in SCALAR_FIELDS:
            v = d.get(key)
            self.entries[key].setText('' if v is None else str(v))
        for key, _ in DICT_FIELDS:
            self.texts[key].setPlainText(', '.join(
                f'{k} {v}'.strip() for k, v in (d.get(key) or {}).items()))
        for key, _ in LIST_FIELDS:
            self.texts[key].setPlainText(', '.join(str(x) for x in (d.get(key) or [])))
        self.texts['traits'].setPlainText('\n'.join(
            f"{t.get('name', '')}. {t.get('desc', '')}".strip('. ')
            for t in (d.get('traits') or [])))

    def get_data(self):
        out = {'ability_scores': {}, 'ability_mods': {}, 'saves': {}, 'skills': {},
               'senses': {}, 'vulnerabilities': [], 'resistances': [], 'immunities': [],
               'condition_immunities': [], 'languages': [], 'cr': None,
               'prof_bonus': None, 'size': None, 'type': None, 'traits': []}
        for key, _ in ABILITY_ROWS:
            s = _int(self.entries['score_' + key].text())
            m = _int(self.entries['mod_' + key].text())
            if s is not None:
                out['ability_scores'][key] = s
            if m is not None:
                out['ability_mods'][key] = m
        for key, _ in SCALAR_FIELDS:
            out[key] = self.entries[key].text().strip() or None
        for key, _ in DICT_FIELDS:
            out[key] = parse_pairs(self.texts[key].toPlainText())
        for key, _ in LIST_FIELDS:
            out[key] = parse_list(self.texts[key].toPlainText())
        out['traits'] = parse_traits(self.texts['traits'].toPlainText())
        return out


class AttackListEditor(QWidget):
    def __init__(self, parent=None, attacks=None):
        super().__init__(parent)
        self.attacks = [dict(a) for a in (attacks or [])]
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.box = QListWidget()
        self.box.setFixedHeight(110)
        self.box.itemDoubleClicked.connect(lambda *_: self.edit())
        lay.addWidget(self.box)
        row = QHBoxLayout()
        for text, fn in (('＋ атака', self.add), ('✎ изменить', self.edit),
                         ('✕ удалить', self.remove)):
            b = QPushButton(text)
            b.setProperty('variant', 'outline')
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.refresh()

    def refresh(self):
        self.box.clear()
        for a in self.attacks:
            self.box.addItem(attack_line(a))

    def add(self):
        d = AttackDialog(self)
        if d.exec() == QDialog.DialogCode.Accepted:
            self.attacks.append(d.data())
            self.refresh()

    def edit(self):
        r = self.box.currentRow()
        if r < 0:
            QMessageBox.warning(self, 'Внимание', 'Выберите атаку!')
            return
        d = AttackDialog(self, self.attacks[r])
        if d.exec() == QDialog.DialogCode.Accepted:
            self.attacks[r] = d.data()
            self.refresh()

    def remove(self):
        r = self.box.currentRow()
        if r >= 0:
            del self.attacks[r]
            self.refresh()


def _scroll(inner):
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setWidget(inner)
    return sa


class CreatureEditDialog(QDialog):
    def __init__(self, parent, enemies):
        super().__init__(parent)
        self.enemies = enemies
        e0 = enemies[0]
        self.setWindowTitle(f'Редактирование {len(enemies)} существ')
        self.resize(640, 800)
        outer = QVBoxLayout(self)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        title = QLabel(f'Правки применятся ко всем выбранным: {len(enemies)}')
        title.setProperty('role', 'title')
        lay.addWidget(title)

        grid = QGridLayout()
        self.name = QLineEdit(e0.name)
        grid.addWidget(QLabel('Имя:'), 0, 0)
        grid.addWidget(self.name, 0, 1)
        self.hp = QSpinBox(); self.hp.setRange(1, 2000); self.hp.setValue(e0.max_hp)
        self.ac = QSpinBox(); self.ac.setRange(1, 40); self.ac.setValue(e0.ac)
        self.spd = QSpinBox(); self.spd.setRange(0, 300); self.spd.setValue(getattr(e0, 'speed', 30))
        self.regen = QSpinBox(); self.regen.setRange(0, 200); self.regen.setValue(getattr(e0, 'regen', 0))
        for r, (lab, w) in enumerate((('Хиты:', self.hp), ('Класс доспеха:', self.ac),
                                      ('Скорость (фт):', self.spd),
                                      ('Регенерация:', self.regen)), start=1):
            grid.addWidget(QLabel(lab), r, 0)
            grid.addWidget(w, r, 1)
        grid.setColumnStretch(2, 1)
        lay.addLayout(grid)

        lay.addWidget(QLabel('Атаки (двойной клик — изменить):'))
        self.atk = AttackListEditor(attacks=[attack_dict(a) for a in e0.attacks])
        lay.addWidget(self.atk)
        self.chars = CharacteristicsEditor(initial={k: getattr(e0, k, None) for k in CHAR_KEYS})
        lay.addWidget(self.chars)
        from conditions import MANUAL_IDS, active_conditions, condition_name, exhaustion_level
        lay.addWidget(QLabel('Состояния (висят, пока не сняты):'))
        grid_c = QGridLayout()
        present = {item.get('id') for item in active_conditions(e0) if isinstance(item, dict)}
        self.cond_boxes = {}
        for index, condition_id in enumerate(MANUAL_IDS):
            box = QCheckBox(condition_name(condition_id))
            box.setChecked(condition_id in present)
            self.cond_boxes[condition_id] = box
            grid_c.addWidget(box, index // 3, index % 3)
        lay.addLayout(grid_c)
        exh = QHBoxLayout()
        exh.addWidget(QLabel('Истощение (0–6):'))
        self.exhaustion = QSpinBox()
        self.exhaustion.setRange(0, 6)
        self.exhaustion.setValue(exhaustion_level(e0))
        exh.addWidget(self.exhaustion)
        exh.addStretch()
        lay.addLayout(exh)
        lay.addStretch()
        outer.addWidget(_scroll(inner), 1)

        row = QHBoxLayout()
        cancel = QPushButton('Отмена')
        cancel.setProperty('variant', 'outline')
        cancel.clicked.connect(self.reject)
        save = QPushButton('💾 Сохранить')
        save.setProperty('variant', 'primary')
        save.clicked.connect(self.apply)
        row.addStretch()
        row.addWidget(cancel)
        row.addWidget(save)
        outer.addLayout(row)

    def apply(self):
        from entities import Attack
        if not self.atk.attacks:
            QMessageBox.warning(self, 'Внимание', 'Нужна хотя бы одна атака!')
            return
        from conditions import sync_manual_conditions
        chars = self.chars.get_data()
        marked = [cid for cid, box in self.cond_boxes.items() if box.isChecked()]
        for e in self.enemies:
            e.name = self.name.text().strip() or e.name
            e.max_hp = self.hp.value()
            e.hp = self.hp.value()
            e.ac = self.ac.value()
            e.speed = self.spd.value()
            e.regen = self.regen.value()
            e.alive = e.hp > 0
            previous = {attack.name: attack for attack in e.attacks}
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
            e.attacks = built
            for k, v in chars.items():
                setattr(e, k, v)
            sync_manual_conditions(e, marked, self.exhaustion.value())
        self.accept()


class SideCreatorDialog(QDialog):
    ready = pyqtSignal(dict)

    def __init__(self, parent, types, mode='create', current_type=None):
        super().__init__(parent)
        self.types = types
        self.mode = mode
        self.multiattack_data = None
        self.setWindowTitle('Кого ведём в бой?' if mode == 'create' else 'Изменить состав')
        self.resize(620, 780)
        outer = QVBoxLayout(self)
        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        choice = QWidget()
        cl = QVBoxLayout(choice)
        cl.addWidget(QLabel('Тактика отряда:'))
        self.strat = QComboBox()
        self.strat.addItems(STRATS)
        cl.addWidget(self.strat)
        hint = QLabel('Выберите, откуда взять существ:')
        hint.setProperty('role', 'title')
        cl.addWidget(hint)
        b1 = QPushButton('📖  Импорт из бестиария\n(тянем статблок с dnd.su)')
        b1.setMinimumHeight(66)
        b1.clicked.connect(self.start_import)
        b2 = QPushButton('🛠  Своё существо\n(характеристики вручную)')
        b2.setMinimumHeight(66)
        b2.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        cl.addWidget(b1)
        cl.addWidget(b2)
        if current_type:
            cur = QLabel(f'Текущий состав: {current_type}')
            cur.setProperty('role', 'muted')
            cl.addWidget(cur)
        cl.addStretch()
        self.stack.addWidget(choice)

        form = QWidget()
        fl = QVBoxLayout(form)
        prow = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.addItems(types)
        load = QPushButton('Загрузить пресет в поля')
        load.setProperty('variant', 'outline')
        load.clicked.connect(self.load_preset)
        prow.addWidget(QLabel('Пресет:'))
        prow.addWidget(self.preset, 1)
        prow.addWidget(load)
        fl.addLayout(prow)

        inner = QWidget()
        il = QVBoxLayout(inner)
        g = QGridLayout()
        self.cname = QLineEdit('')
        g.addWidget(QLabel('Имя существа:'), 0, 0)
        g.addWidget(self.cname, 0, 1)
        self.chp = QSpinBox(); self.chp.setRange(1, 2000); self.chp.setValue(10)
        self.cac = QSpinBox(); self.cac.setRange(1, 40); self.cac.setValue(10)
        self.cspd = QSpinBox(); self.cspd.setRange(0, 300); self.cspd.setValue(30)
        self.cregen = QSpinBox(); self.cregen.setRange(0, 200); self.cregen.setValue(0)
        for r, (lab, w) in enumerate((('Хиты:', self.chp), ('Класс доспеха:', self.cac),
                                      ('Скорость (фт):', self.cspd),
                                      ('Регенерация:', self.cregen)), start=1):
            g.addWidget(QLabel(lab), r, 0)
            g.addWidget(w, r, 1)
        g.setColumnStretch(2, 1)
        il.addLayout(g)
        il.addWidget(QLabel('Атаки:'))
        self.atk = AttackListEditor()
        il.addWidget(self.atk)
        self.chars = CharacteristicsEditor()
        il.addWidget(self.chars)
        il.addStretch()
        fl.addWidget(_scroll(inner), 1)

        bottom = QHBoxLayout()
        back = QPushButton('← Назад')
        back.setProperty('variant', 'outline')
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        create = QPushButton('✅ Создать сторону')
        create.setProperty('variant', 'primary')
        create.clicked.connect(self.confirm)
        bottom.addWidget(back)
        bottom.addStretch()
        bottom.addWidget(create)
        fl.addLayout(bottom)
        self.stack.addWidget(form)

    def start_import(self):
        from qt_bestiary import BestiaryDialog
        d = BestiaryDialog(self)
        d.imported.connect(self._imported)
        d.exec()

    def _imported(self, type_name):
        self.ready.emit({'army_type': type_name, 'strategy': self.strat.currentText()})
        self.accept()

    def load_preset(self):
        tmp = EnemyFactory.create_enemy(self.preset.currentText(), '_preset_', 0)
        self.multiattack_data = getattr(tmp, 'multiattack', None)
        self.cname.setText(self.preset.currentText())
        self.chp.setValue(tmp.max_hp)
        self.cac.setValue(tmp.ac)
        self.cspd.setValue(getattr(tmp, 'speed', 30))
        self.cregen.setValue(getattr(tmp, 'regen', 0))
        self.atk.attacks = [attack_dict(a) for a in tmp.attacks]
        self.atk.refresh()
        self.chars.set_data({k: getattr(tmp, k, None) for k in CHAR_KEYS})
        self._kept_card = {
            'legendary_actions': getattr(tmp, 'legendary_actions', None),
            'legendary_resistance': getattr(tmp, 'legendary_resistance', None),
            'lair_actions': getattr(tmp, 'lair_actions', None),
            'special_actions': list(getattr(tmp, 'special_actions', None) or []),
            'bonus_actions': list(getattr(tmp, 'bonus_actions', None) or []),
            'reactions': list(getattr(tmp, 'reactions', None) or []),
        }

    def confirm(self):
        name = self.cname.text().strip()
        if not name:
            QMessageBox.warning(self, 'Внимание', 'Дайте существу имя!')
            return
        if not self.atk.attacks:
            QMessageBox.warning(self, 'Внимание', 'Добавьте хотя бы одну атаку!')
            return
        kept = {key: value for key, value in getattr(self, '_kept_card', {}).items() if value}
        EnemyFactory.register_type(name, hp=self.chp.value(), ac=self.cac.value(),
                                   attacks=self.atk.attacks, speed=self.cspd.value(),
                                   regen=self.cregen.value(),
                                   multiattack=self.multiattack_data,
                                   **self.chars.get_data(), **kept)
        self.ready.emit({'army_type': name, 'strategy': self.strat.currentText()})
        self.accept()