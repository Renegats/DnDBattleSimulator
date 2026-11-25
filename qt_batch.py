"""Диалог пакетной симуляции. Считает в фоне через qt_async, окно не блокирует."""
import qt_async
from monte_carlo import run_batch, summary_lines, write_csv
from qt_theme import current_palette

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog,
                             QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                             QMessageBox, QProgressBar, QPushButton,
                             QScrollArea, QSpinBox, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)


def _run(snapshot, options, progress, cancel):
    return run_batch(snapshot, progress=progress, cancel=cancel, **options)


def _pct(rate):
    return f'{rate * 100:.1f}%'


def _ci(low, high):
    return f'{low * 100:.1f}–{high * 100:.1f}%'


def _num(value):
    if value is None:
        return '—'
    return f'{value:.1f}'


class RoundHistogram(QWidget):
    """Столбики: по горизонтали число раундов, по вертикали сколько боёв."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('batch_hist')
        self.setMinimumHeight(168)
        self._pairs = []

    def set_histogram(self, pairs):
        self._pairs = list(pairs or [])
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            palette = current_palette()
            bg = QColor(palette['bg'])
            fg = QColor(palette['fg'])
            muted = QColor(palette['fg_muted'])
            accent = QColor(palette['accent'])
            painter.fillRect(self.rect(), bg)
            if not self._pairs:
                painter.setPen(muted)
                painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, 'Нет данных')
                return
            rect = QRectF(self.rect().adjusted(12, 12, -12, -26))
            if rect.width() < 8 or rect.height() < 8:
                return
            peak = max(count for _rounds, count in self._pairs) or 1
            count = len(self._pairs)
            gap = 3.0 if count < 30 else 1.0
            bar_w = max(1.0, (rect.width() - gap * (count - 1)) / count)
            painter.setPen(muted)
            painter.drawLine(int(rect.left()), int(rect.bottom()),
                             int(rect.right()), int(rect.bottom()))
            font = painter.font()
            font.setPointSize(8)
            painter.setFont(font)
            for index, (rounds, value) in enumerate(self._pairs):
                height = rect.height() * (value / peak) if value else 0
                left = rect.left() + index * (bar_w + gap)
                painter.fillRect(QRectF(left, rect.bottom() - height, bar_w, height), accent)
                show = count <= 16 or index in (0, count - 1) or (
                    count <= 32 and rounds % 2 == 0)
                if show:
                    painter.setPen(fg)
                    painter.drawText(
                        QRectF(left - 6, rect.bottom() + 2, bar_w + 12, 18),
                        Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                        str(rounds))
                    painter.setPen(muted)
        finally:
            painter.end()


class BatchDialog(QDialog):
    """N, сид, лимит раундов, прогресс, отмена, таблица и гистограмма."""

    def __init__(self, parent, snapshot, auto_move=True, crit_mode='double_all'):
        super().__init__(parent)
        self.setObjectName('batch_dialog')
        self.setWindowTitle('Пакетная симуляция')
        self.setModal(False)
        self.resize(980, 820)
        self._snapshot = snapshot
        self._guard = qt_async.Guard()
        self._cancel = None
        self._running = False
        self._report = None

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)
        hint = QLabel(
            'Каждый бой начинается с копии текущей сцены: состояния, перезарядка, '
            'легендарные действия и сопротивление сохраняются. Сам бой на экране не меняется. '
            'Журнал в пакете не пишется. Сид боя зависит только от базового сида и номера.')
        hint.setWordWrap(True)
        hint.setProperty('role', 'muted')
        root.addWidget(hint)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        self.battles = QSpinBox()
        self.battles.setObjectName('batch_n')
        self.battles.setRange(1, 100000)
        self.battles.setValue(1000)
        self.battles.setSuffix(' боёв')
        self.battles.valueChanged.connect(self._sync_progress)
        form.addRow('Число боёв', self.battles)

        self.seed = QSpinBox()
        self.seed.setObjectName('batch_seed')
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(1)
        form.addRow('Базовый сид', self.seed)

        self.rounds = QSpinBox()
        self.rounds.setObjectName('batch_rounds')
        self.rounds.setRange(1, 1000)
        self.rounds.setValue(40)
        self.rounds.setSuffix(' раундов')
        form.addRow('Лимит раундов', self.rounds)

        self.workers = QSpinBox()
        self.workers.setObjectName('batch_workers')
        self.workers.setRange(1, 32)
        self.workers.setValue(1)
        self.workers.setToolTip('1 — в этом процессе. Больше — отдельные процессы.')
        form.addRow('Процессы', self.workers)

        self.auto_move = QCheckBox('Автоперемещение')
        self.auto_move.setObjectName('batch_auto')
        self.auto_move.setChecked(bool(auto_move))
        form.addRow('', self.auto_move)

        self.crit = QComboBox()
        self.crit.setObjectName('batch_crit')
        self.crit.addItem('Удваивать весь урон', 'double_all')
        self.crit.addItem('Удваивать только кости', 'dice_only')
        index = self.crit.findData(crit_mode or 'double_all')
        self.crit.setCurrentIndex(index if index >= 0 else 0)
        form.addRow('Крит', self.crit)
        root.addLayout(form)

        buttons = QHBoxLayout()
        self.start_btn = QPushButton('Запустить')
        self.start_btn.setObjectName('batch_start')
        self.start_btn.setProperty('variant', 'primary')
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton('Отмена')
        self.cancel_btn.setObjectName('batch_cancel')
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)
        self.export_btn = QPushButton('Экспорт CSV…')
        self.export_btn.setObjectName('batch_export')
        self.export_btn.setEnabled(False)
        self.export_btn.setToolTip('UTF-8 с BOM, разделитель — точка с запятой')
        self.export_btn.clicked.connect(self.export_csv)
        buttons.addWidget(self.start_btn)
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.export_btn)
        buttons.addStretch()
        root.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setObjectName('batch_progress')
        self.progress.setRange(0, self.battles.value())
        self.progress.setValue(0)
        self.progress.setFormat('%v из %m')
        self.progress.setTextVisible(True)
        root.addWidget(self.progress)
        self.status_lbl = QLabel('Снимок сцены готов.')
        self.status_lbl.setObjectName('batch_status')
        self.status_lbl.setWordWrap(True)
        root.addWidget(self.status_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setObjectName('batch_scroll')
        host = QWidget()
        self.results_host = host
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self.summary = QLabel('')
        self.summary.setObjectName('batch_summary')
        self.summary.setWordWrap(True)
        body.addWidget(self.summary)
        body.addWidget(QLabel('Распределение раундов'))
        self.histogram = RoundHistogram()
        body.addWidget(self.histogram)
        body.addWidget(QLabel('Исходы'))
        self.side_table = self._table(
            'batch_sides',
            ['Исход', 'Количество', 'Доля', '95% интервал'])
        body.addWidget(self.side_table)
        body.addWidget(QLabel('Существа'))
        self.creature_table = self._table(
            'batch_creatures',
            ['Существо', 'Сторона', 'Выживание', 'Средние хиты',
             'Хиты живых', 'Урон нанесён', 'Урон получен'])
        body.addWidget(self.creature_table)
        body.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

    @staticmethod
    def _table(name, headers):
        table = QTableWidget(0, len(headers))
        table.setObjectName(name)
        table.setHorizontalHeaderLabels(headers)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(False)
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        return table

    def _sync_progress(self, value):
        if not self._running:
            self.progress.setRange(0, max(1, int(value)))
            self.progress.setValue(0)

    @staticmethod
    def _fit_table(table, cap=14):
        rows = table.rowCount()
        header = table.horizontalHeader().height() or 28
        row_h = table.rowHeight(0) if rows else 28
        if row_h < 8:
            row_h = 28
        shown = min(max(rows, 1), cap)
        height = header + row_h * shown + 6
        table.setMinimumHeight(height)
        table.setMaximumHeight(height if rows <= cap else header + row_h * cap + 6)

    def start(self):
        if self._running:
            return
        self._running = True
        self._report = None
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        battles = int(self.battles.value())
        self.progress.setRange(0, battles)
        self.progress.setValue(0)
        self.status_lbl.setText('Считаю…')
        self.summary.setText('')
        self.histogram.set_histogram([])
        self.side_table.setRowCount(0)
        self.creature_table.setRowCount(0)
        options = {
            'battles': battles,
            'seed': int(self.seed.value()),
            'max_rounds': int(self.rounds.value()),
            'auto_move': self.auto_move.isChecked(),
            'crit_mode': self.crit.currentData() or 'double_all',
            'workers': int(self.workers.value()),
        }
        self._cancel = qt_async.submit_cancellable(
            _run, args=(self._snapshot, options),
            on_ok=self._on_ok, on_fail=self._on_fail, on_progress=self._on_progress,
            guard=self._guard)

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
        self.cancel_btn.setEnabled(False)
        if self._running:
            self.status_lbl.setText('Останавливаю…')

    def export_csv(self):
        if self._report is None or self._report.battles_done <= 0:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self, 'Экспорт CSV', 'monte_carlo.csv', 'CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            write_csv(path, self._report)
        except OSError as exc:
            QMessageBox.critical(self, 'Экспорт CSV', str(exc))
            return
        self.status_lbl.setText(f'CSV сохранён: {path}')

    def _on_progress(self, payload):
        done = int(payload.get('done') or 0)
        total = int(payload.get('total') or 0)
        if total > 0:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        bits = [f'{name} {count}' for name, count in zip(
            payload.get('side_names') or [], payload.get('wins') or [])]
        tail = (f" · ничьи {payload.get('draws', 0)}"
                f" · таймауты {payload.get('timeouts', 0)}")
        head = ' · '.join(bits)
        self.status_lbl.setText(f'{done} из {total}' + (f' · {head}{tail}' if head else ''))

    def _on_ok(self, report):
        self._running = False
        self._report = report
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.export_btn.setEnabled(report.battles_done > 0)
        self.progress.setRange(0, max(1, report.battles_requested))
        self.progress.setValue(report.battles_done)
        self.show_report(report)

    def _on_fail(self, message):
        self._running = False
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.status_lbl.setText('Ошибка')
        QMessageBox.critical(self, 'Пакетная симуляция', str(message))

    def show_report(self, report):
        self.summary.setText('\n'.join(summary_lines(report)))
        self.histogram.set_histogram(report.round_histogram)
        stats = list(report.sides) + [report.draw, report.timeout]
        self._fill(self.side_table, [
            [stat.name, str(stat.count), _pct(stat.rate), _ci(stat.ci_low, stat.ci_high)]
            for stat in stats
        ])
        self._fill(self.creature_table, [
            [creature.name, creature.side_name, _pct(creature.survival),
             _num(creature.mean_hp), _num(creature.mean_hp_alive),
             _num(creature.mean_dealt), _num(creature.mean_taken)]
            for creature in report.creatures
        ])
        self._fit_table(self.side_table, cap=8)
        self._fit_table(self.creature_table, cap=14)
        if report.cancelled:
            self.status_lbl.setText(
                f'Отменено. Посчитано боёв: {report.battles_done} из {report.battles_requested}.')
        else:
            self.status_lbl.setText(f'Готово: {report.battles_done} боёв.')

    @staticmethod
    def _fill(table, rows):
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                if column:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(row_index, column, item)

    def closeEvent(self, event):
        self._guard.drop()
        if self._cancel is not None:
            self._cancel.set()
        super().closeEvent(event)
