"""Импорт монстров из бестиария: структурированный предпросмотр, всегда видимый футер.

Два исправления по существу:
  * окно вписывается в доступную геометрию экрана и центрируется на родителе,
    футер с кнопками закреплён снизу — прокручивается только предпросмотр;
  * в фоновом потоке выполняется не только запрос, но и разбор статблока
    (раньше parse_statblock шёл в GUI-потоке и вешал окно на секунды).
"""
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                             QLineEdit, QPushButton, QListWidget, QScrollArea,
                             QGroupBox, QMessageBox, QSplitter, QWidget, QFrame,
                             QTableWidget, QTableWidgetItem, QHeaderView, QApplication)

import bestiary_core
import portraits
import qt_async
from factory import EnemyFactory
from qt_theme import current_palette
from statblock_parser import ABILITY_ORDER, ABILITY_LABEL

SPIN = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
CHAR_KEYS = ('ability_scores', 'ability_mods', 'saves', 'skills', 'senses',
             'vulnerabilities', 'resistances', 'immunities', 'condition_immunities',
             'languages', 'cr', 'prof_bonus', 'size', 'type', 'traits',
             'legendary_actions', 'legendary_resistance', 'lair_actions',
             'special_actions', 'bonus_actions', 'reactions')


class BestiaryDialog(QDialog):
    imported = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pal = current_palette()
        self.setWindowTitle('📖 Импорт монстров из бестиария')
        self.setSizeGripEnabled(True)
        self._guard = qt_async.Guard()
        self._req = 0
        self._pic_req = 0
        self._results = []
        self._monster = None
        self._pic_index = 0
        self._spin_i = 0
        self._busy_text = ''

        self._build()
        self._fit_screen(parent)

        self._timer = QTimer(self)
        self._timer.setInterval(90)
        self._timer.timeout.connect(self._tick)

    # ================= каркас =================
    def _build(self):
        p = self.pal
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(10)

        search = QGroupBox('Поиск монстра')
        sr = QHBoxLayout(search)
        sr.setSpacing(8)
        self.query = QLineEdit()
        self.query.setPlaceholderText('демогоргон, щитостраж, древний красный дракон…')
        self.query.setMinimumHeight(32)
        self.query.returnPressed.connect(self.search)
        self.btn_search = QPushButton('🔍  Искать')
        self.btn_search.setProperty('variant', 'primary')
        self.btn_search.setMinimumHeight(32)
        self.btn_search.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_search.clicked.connect(self.search)
        sr.addWidget(QLabel('Название:'))
        sr.addWidget(self.query, 1)
        sr.addWidget(self.btn_search)
        lay.addWidget(search)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        rbox = QGroupBox('Результаты поиска')
        rl = QVBoxLayout(rbox)
        self.list = QListWidget()
        self.list.setMinimumWidth(230)
        self.list.currentRowChanged.connect(self.pick)
        self.list.itemDoubleClicked.connect(lambda *_: self.pick(self.list.currentRow()))
        rl.addWidget(self.list)
        self.count_lbl = QLabel('Ничего не искали.')
        self.count_lbl.setProperty('role', 'muted')
        rl.addWidget(self.count_lbl)
        split.addWidget(rbox)

        pbox = QGroupBox('Предпросмотр статблока')
        pl = QVBoxLayout(pbox)
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_host = QWidget()
        self.preview_lay = QVBoxLayout(self.preview_host)
        self.preview_lay.setContentsMargins(10, 10, 12, 10)
        self.preview_lay.setSpacing(10)
        self.preview_scroll.setWidget(self.preview_host)
        pl.addWidget(self.preview_scroll)
        split.addWidget(pbox)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 720])
        lay.addWidget(split, 1)

        foot = QFrame()
        foot.setProperty('role', 'bar')
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(10, 8, 10, 8)
        self.status = QLabel('Введите название и нажмите «Искать».')
        self.status.setStyleSheet(f"color: {p['fg_muted']};")
        fl.addWidget(self.status, 1)
        close = QPushButton('Закрыть')
        close.setProperty('variant', 'outline')
        close.setMinimumHeight(34)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        self.btn_import = QPushButton('✨  Импортировать в симулятор')
        self.btn_import.setProperty('variant', 'primary')
        self.btn_import.setMinimumHeight(34)
        self.btn_import.setMinimumWidth(230)
        self.btn_import.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_import.setEnabled(False)
        self.btn_import.clicked.connect(self.do_import)
        fl.addWidget(close)
        fl.addWidget(self.btn_import)
        lay.addWidget(foot, 0)

        self._placeholder('Здесь появится статблок: портрет, характеристики, '
                          'атаки, защиты и особенности монстра.')

    def _fit_screen(self, parent):
        screen = self.screen() or QApplication.primaryScreen()
        av = screen.availableGeometry()
        w = min(1180, int(av.width() * 0.94))
        h = min(780, int(av.height() * 0.88))
        self.setMinimumSize(min(760, av.width() - 40), min(460, av.height() - 40))
        self.setMaximumSize(av.width(), av.height())
        self.resize(w, h)
        if parent is not None:
            c = parent.frameGeometry().center()
        else:
            c = av.center()
        x = max(av.left(), min(av.right() - w, c.x() - w // 2))
        y = max(av.top(), min(av.bottom() - h, c.y() - h // 2))
        self.move(x, y)

    def showEvent(self, e):
        super().showEvent(e)
        self._fit_screen(self.parentWidget())

    # =================Busy =================
    def _busy(self, on, text=''):
        self.btn_search.setEnabled(not on)
        self.query.setEnabled(not on)
        self.list.setEnabled(not on)
        self._busy_text = text
        if on:
            self._spin_i = 0
            self._timer.start()
            self._tick()
        else:
            self._timer.stop()
            self.status.setText(text)

    def _tick(self):
        self._spin_i = (self._spin_i + 1) % len(SPIN)
        self.status.setText(f'{SPIN[self._spin_i]}  {self._busy_text}')

    def _placeholder(self, text):
        self._clear_preview()
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setProperty('role', 'muted')
        self.preview_lay.addWidget(lab)
        self.preview_lay.addStretch()

    def _clear_preview(self):
        while self.preview_lay.count():
            it = self.preview_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                self._clear_sub(it.layout())

    def _clear_sub(self, lay):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
            elif it.layout() is not None:
                self._clear_sub(it.layout())

    # ================= поиск =================
    def _fail(self, msg):
        self._busy(False, 'Ошибка сети.')
        QMessageBox.critical(self, 'Ошибка сети', f'Не удалось получить данные:\n{msg}')

    def search(self):
        q = self.query.text().strip()
        if not q:
            QMessageBox.warning(self, 'Внимание', 'Введите название монстра!')
            return
        self._req += 1
        token = self._req
        self._monster = None
        self.btn_import.setEnabled(False)
        self._results = []
        self.list.blockSignals(True)
        self.list.clear()
        self.list.blockSignals(False)
        self.count_lbl.setText('Идёт поиск…')
        self._placeholder('⏳ Ищем на dnd.su…')
        self._busy(True, 'Идёт поиск…')

        def work():
            return bestiary_core.search_monsters(bestiary_core.fetch_search(q), q)

        qt_async.submit(work, (), on_ok=lambda res: self._got_search(res, token),
                        on_fail=self._fail, guard=self._guard)

    def _got_search(self, results, token):
        if token != self._req:
            return
        self._results = results
        self.list.blockSignals(True)
        self.list.clear()
        for e in results:
            self.list.addItem(e['name'])
        self.list.blockSignals(False)
        self._busy(False, '')
        if not results:
            self.count_lbl.setText('Ничего не найдено.')
            self._placeholder('Монстры с таким именем не найдены. Попробуйте другое название.')
            self.status.setText('Ничего не найдено.')
            return
        self.count_lbl.setText(f'Найдено: {len(results)}')
        self.status.setText('Выберите монстра в списке слева.')
        self.list.setCurrentRow(0)

    # ================= статблок =================
    def pick(self, row):
        if row < 0 or row >= len(self._results):
            return
        entry = self._results[row]
        self._req += 1
        token = self._req
        self._monster = None
        self.btn_import.setEnabled(False)
        self._placeholder(f'⏳ Загружаем и разбираем статблок «{entry["name"]}»…')
        self._busy(True, 'Загрузка статблока…')
        qt_async.submit(bestiary_core.load_monster, (entry['url'],),
                        on_ok=lambda m: self._got_block(m, token),
                        on_fail=self._fail, guard=self._guard)

    def _got_block(self, m, token):
        if token != self._req:
            return
        self._monster = m
        self._busy(False, '')
        self._render_monster(m)
        self.btn_import.setEnabled(True)
        pics = len(m.get('portraits') or [])
        notes = len(m.get('warnings') or []) + len(m.get('errors') or [])
        tail = f'  ·  картинок в галерее: {pics}' if pics else '  ·  без галереи'
        if notes:
            tail += f'  ·  предупреждений: {notes}'
        self.status.setText(f"Готов к импорту: {m['name']}{tail}")

    def _chip(self, text, tone):
        lab = QLabel(text)
        lab.setStyleSheet(
            f"background: {self.pal['field_bg']}; color: {tone};"
            f"border: 1px solid {self.pal['border']}; border-radius: 9px;"
            f"padding: 4px 10px; font-weight: bold;")
        return lab

    def _section(self, title):
        cap = QLabel(title)
        cap.setStyleSheet(f"color: {self.pal['accent']}; font-weight: bold; font-size: 11pt;")
        self.preview_lay.addWidget(cap)

    def _kv(self, label, value):
        if not value:
            return
        row = QHBoxLayout()
        k = QLabel(label + ':')
        k.setStyleSheet(f"color: {self.pal['fg_muted']};")
        k.setMinimumWidth(150)
        v = QLabel(value)
        v.setWordWrap(True)
        row.addWidget(k, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(v, 1)
        self.preview_lay.addLayout(row)

    def _render_monster(self, m):
        p = self.pal
        self._clear_preview()
        problems = [(p['danger'], item) for item in (m.get('errors') or [])]
        problems += [(p['warning'], item) for item in (m.get('warnings') or [])]
        if problems:
            box = QLabel('\n'.join(f'⚠ {item}' for _tone, item in problems))
            box.setObjectName('importWarnings')
            box.setWordWrap(True)
            box.setStyleSheet(
                f"background: {p['field_bg']}; color: {p['fg']};"
                f"border: 2px solid {p['warning']}; border-radius: 8px; padding: 8px;")
            self.preview_lay.addWidget(box)
            note = QLabel('Импорт не заблокирован: карточку можно забрать и поправить в редакторе.')
            note.setWordWrap(True)
            note.setProperty('role', 'muted')
            self.preview_lay.addWidget(note)

        head = QHBoxLayout()
        head.setSpacing(12)
        self.pic = QLabel('нет портрета')
        self.pic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.pic.setFixedSize(168, 210)
        self.pic.setStyleSheet(
            f"background: {p['field_bg']}; color: {p['fg_muted']};"
            f"border: 1px solid {p['border']}; border-radius: 10px;")
        head.addWidget(self.pic, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.setSpacing(7)
        name = QLabel(m['name'])
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {p['fg']}; font-size: 16pt; font-weight: bold;")
        right.addWidget(name)
        meta = ' · '.join(str(x) for x in (m.get('size'), m.get('type')) if x)
        if m.get('cr'):
            meta += f" · CR {m['cr']}"
        if m.get('prof_bonus'):
            meta += f" · мастерство {m['prof_bonus']}"
        if meta:
            ml = QLabel(meta)
            ml.setWordWrap(True)
            ml.setStyleSheet(f"color: {p['fg_muted']};")
            right.addWidget(ml)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.addWidget(self._chip(f"❤ {m['hp']} HP", p['danger']))
        chips.addWidget(self._chip(f"🛡 {m['ac']} AC", p['accent']))
        chips.addWidget(self._chip(f"👟 {m.get('speed', 30)} фт", p['success']))
        if m.get('regen'):
            chips.addWidget(self._chip(f"💚 +{m['regen']}/раунд", p['warning']))
        chips.addStretch()
        right.addLayout(chips)

        sc, md = m.get('ability_scores') or {}, m.get('ability_mods') or {}
        if sc:
            ab = QHBoxLayout()
            ab.setSpacing(6)
            for k in ABILITY_ORDER:
                if k not in sc:
                    continue
                card = QFrame()
                card.setStyleSheet(
                    f"background: {p['field_bg']}; border: 1px solid {p['border']};"
                    f"border-radius: 9px;")
                cl = QVBoxLayout(card)
                cl.setContentsMargins(8, 5, 8, 5)
                cl.setSpacing(0)
                t = QLabel(ABILITY_LABEL[k])
                t.setAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setStyleSheet(f"color: {p['accent']}; font-size: 8pt; font-weight: bold; border: none;")
                s = QLabel(str(sc[k]))
                s.setAlignment(Qt.AlignmentFlag.AlignCenter)
                s.setStyleSheet(f"color: {p['fg']}; font-size: 13pt; font-weight: bold; border: none;")
                mv = md.get(k, 0)
                d = QLabel(f"{'+' if mv >= 0 else ''}{mv}")
                d.setAlignment(Qt.AlignmentFlag.AlignCenter)
                d.setStyleSheet(f"color: {p['fg_muted']}; font-size: 8pt; border: none;")
                cl.addWidget(t); cl.addWidget(s); cl.addWidget(d)
                ab.addWidget(card)
            ab.addStretch()
            right.addLayout(ab)

        prow = QHBoxLayout()
        self.btn_pic = QPushButton('🎲 Другая картинка')
        self.btn_pic.setProperty('variant', 'outline')
        self.btn_pic.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_pic.clicked.connect(lambda: self._load_portrait(self._pic_index + 1))
        self.pic_info = QLabel('')
        self.pic_info.setStyleSheet(f"color: {p['fg_muted']};")
        prow.addWidget(self.btn_pic)
        prow.addWidget(self.pic_info, 1)
        right.addLayout(prow)
        right.addStretch()
        head.addLayout(right, 1)
        self.preview_lay.addLayout(head)

        self._section('⚔️ Атаки')
        if m.get('multiattack'):
            ma = QLabel('Мультиатака: ' + ' + '.join(
                f"{s['attack']}×{s.get('count', 1)}" for s in m['multiattack']))
            ma.setWordWrap(True)
            ma.setStyleSheet(f"color: {p['warning']};")
            self.preview_lay.addWidget(ma)
        atks = m.get('attacks') or []
        table = QTableWidget(len(atks), 5)
        table.setHorizontalHeaderLabels(['Атака', 'Попадание', 'Урон', 'Тип', 'Дальность'])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        hh = table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for r, a in enumerate(atks):
            mark = ' ✦' if a.get('magical') else ''
            dmg = bestiary_core.format_damage(a)
            for c, val in enumerate((a['name'] + mark, f"{a['attack_bonus']:+d}", dmg,
                                     a.get('damage_type') or '—',
                                     f"{a.get('range_ft', 5)} фт")):
                table.setItem(r, c, QTableWidgetItem(str(val)))
        table.setFixedHeight(min(210, 30 * (len(atks) + 1) + 12))
        self.preview_lay.addWidget(table)

        legendary = m.get('legendary_actions') or None
        if legendary:
            self._section('👑 Легендарные действия')
            cap = QLabel(f"За раунд: {legendary.get('per_round')}. "
                         'В конце чужого хода тратится вариант, который бьёт известной атакой.')
            cap.setWordWrap(True)
            self.preview_lay.addWidget(cap)
            for option in legendary.get('options') or []:
                mark = ' · в бою' if option.get('usable') else ' · только в карточке'
                line = QLabel(f"{option.get('name')} (стоит {option.get('cost', 1)}){mark}. "
                              f"{option.get('desc', '')}")
                line.setWordWrap(True)
                self.preview_lay.addWidget(line)
        resist = m.get('legendary_resistance')
        if resist:
            self._kv('Легендарное сопротивление',
                     f"{resist.get('count')}/день. {resist.get('desc', '')}")
        lair = m.get('lair_actions') or None
        if lair and (lair.get('actions') or lair.get('intro')):
            self._section('🕳 Действия логова')
            hint = QLabel('Сохранены в карточке. Симулятор их не разыгрывает.')
            hint.setWordWrap(True)
            hint.setProperty('role', 'muted')
            self.preview_lay.addWidget(hint)
            for action in (lair.get('actions') or [])[:6]:
                line = QLabel(action)
                line.setWordWrap(True)
                self.preview_lay.addWidget(line)
        specials = m.get('special_actions') or []
        if specials:
            self._section('Особые действия')
            hint = QLabel('Нет броска атаки — в раунде не выполняются, текст сохранён.')
            hint.setWordWrap(True)
            hint.setProperty('role', 'muted')
            self.preview_lay.addWidget(hint)
            for action in specials:
                line = QLabel(f"{action.get('name')}. {action.get('desc', '')}")
                line.setWordWrap(True)
                self.preview_lay.addWidget(line)

        self._section('🛡 Защиты и чувства')
        self._kv('Уязвимости', ', '.join(m.get('vulnerabilities') or []))
        self._kv('Сопротивления', ', '.join(m.get('resistances') or []))
        self._kv('Иммунитеты', ', '.join(m.get('immunities') or []))
        self._kv('Иммун. к условиям', ', '.join(m.get('condition_immunities') or []))
        self._kv('Спасброски', ', '.join(f'{k} {v}' for k, v in (m.get('saves') or {}).items()))
        self._kv('Навыки', ', '.join(f'{k} {v}' for k, v in (m.get('skills') or {}).items()))
        self._kv('Чувства', ', '.join(f'{k} {v}' for k, v in (m.get('senses') or {}).items()))
        self._kv('Языки', ', '.join(m.get('languages') or []))

        traits = m.get('traits') or []
        if traits:
            self._section('✨ Особенности')
            for tr in traits:
                t = QLabel(f"<b>{tr.get('name', '')}.</b> {tr.get('desc', '')}")
                t.setWordWrap(True)
                t.setTextFormat(Qt.TextFormat.RichText)
                self.preview_lay.addWidget(t)
        self.preview_lay.addStretch()
        self._pic_index = 0
        self._load_portrait(0)

    # ================= портрет =================
    def _load_portrait(self, index, tries=0):
        m = self._monster or {}
        urls = m.get('portraits') or []
        if not urls:
            self.btn_pic.setEnabled(False)
            self.pic_info.setText('галерея пуста')
            self.pic.setText('нет портрета')
            return
        i = index % len(urls)
        self._pic_index = i
        self._pic_req += 1
        token = self._pic_req
        self.btn_pic.setEnabled(len(urls) > 1)
        self.pic_info.setText(f'картинка {i + 1} / {len(urls)} · загрузка…')
        self.pic.setText('⏳')
        qt_async.submit(portraits.download, (urls[i],),
                        on_ok=lambda path: self._got_pic(path, i, len(urls), token, tries),
                        on_fail=lambda msg: self._pic_failed(msg, token),
                        guard=self._guard)

    def _got_pic(self, path, index, total, token, tries):
        if token != self._pic_req:
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.pic.setText('не читается')
            self.pic_info.setText(f'картинка {index + 1} / {total}')
            return
        if min(pix.width(), pix.height()) < 240 and total > 1 and tries < total - 1:
            self._load_portrait(index + 1, tries + 1)
            return
        self.pic.setPixmap(pix.scaled(self.pic.width() - 8, self.pic.height() - 8,
                                      Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation))
        self.pic_info.setText(f'картинка {index + 1} / {total} · {pix.width()}×{pix.height()}')

    def _pic_failed(self, msg, token):
        if token != self._pic_req:
            return
        self.pic.setText('нет портрета')
        self.pic_info.setText('картинка не загрузилась')

    # ================= импорт =================
    def do_import(self):
        m = self._monster
        if not m:
            return
        chars = {k: v for k, v in m.items() if k in CHAR_KEYS}
        EnemyFactory.register_type(
            m['name'], hp=m['hp'], ac=m['ac'], attacks=m['attacks'],
            speed=m.get('speed', 30), regen=m.get('regen', 0),
            multiattack=m.get('multiattack'), **chars)
        urls = m.get('portraits') or []
        portraits.set_urls(m['name'], urls)
        if urls:
            portraits.pick(m['name'], self._pic_index)
        self.imported.emit(m['name'])
        self.accept()

    # ================= жизненный цикл =================
    def closeEvent(self, e):
        self._guard.drop()
        self._timer.stop()
        super().closeEvent(e)

    def reject(self):
        self._guard.drop()
        self._timer.stop()
        super().reject()

    def accept(self):
        self._guard.drop()
        self._timer.stop()
        super().accept()