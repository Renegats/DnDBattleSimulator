"""Qt-спайк карты боя (параллельный фронтенд поверх готового ядра).

Что доказывает:
  1. Модель поля (BattleMap) и фабрика (EnemyFactory) не знают о GUI:
     одни и те же объекты кормят и Tkinter-canvas, и QGraphicsScene.
  2. Qt даёт из коробки то, что в Tkinter писали руками: зум колесом,
     панорамирование, сглаживание — без canvasx/scrollregion.

Запуск из корня проекта:  python qt_map_spike.py
Управление: колесо - зум к курсору, тянуть пустое место - панорама,
клик по токену - данные существа внизу окна.
"""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (QApplication, QGraphicsEllipseItem, QGraphicsScene,
                             QGraphicsView, QLabel, QVBoxLayout, QWidget)

# Модель живёт в модуле без tkinter; fallback на случай старой раскладки.
try:
    from battle_map_model import BattleMap
except ImportError:
    from battle_map import BattleMap
from factory import EnemyFactory

CELL = 28                        # как в Tkinter-версии, чтобы сравнивать на глаз
SIDE_COLORS = ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22']
BG = '#2b2d31'                   # палитра тёмной темы из theme_manager хардкодом:
GRID = '#383b40'                 # импорт менеджера тем затянул бы tkinter в спайк


class MapView(QGraphicsView):
    """Холст: зум колесом к курсору, панорама по пустому месту, клик по токену."""

    def __init__(self, scene, on_pick):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(QColor(BG))
        self._on_pick = on_pick
        self._panning = False
        self._pan_last = None
        self._selected = None

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)          # зум к курсору (якорь выше)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.pos())
            if item is not None:
                item = item.topLevelItem()  # клик по подписи = клик по токену
                if item.data(0) is not None:
                    self._select(item)
                    return
            self._panning = True            # пустое место - панорама
            self._pan_last = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning:
            d = event.pos() - self._pan_last
            self._pan_last = event.pos()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - d.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - d.y())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def _select(self, item):
        if self._selected is not None:
            self._selected.setPen(QPen(QColor('black'), 1))
        self._selected = item
        item.setPen(QPen(QColor('white'), 2))
        self._on_pick(item.data(0))


def build_scene(bm, sides):
    scene = QGraphicsScene(0, 0, bm.width * CELL, bm.height * CELL)
    scene.setBackgroundBrush(QColor(BG))
    grid_pen = QPen(QColor(GRID), 1)
    for x in range(bm.width + 1):
        scene.addLine(x * CELL, 0, x * CELL, bm.height * CELL, grid_pen)
    for y in range(bm.height + 1):
        scene.addLine(0, y * CELL, bm.width * CELL, y * CELL, grid_pen)

    font = QFont('Arial', 8, QFont.Weight.Bold)
    for i, side in enumerate(sides):
        color = QColor(SIDE_COLORS[i % len(SIDE_COLORS)])
        for enemy in side:
            pos = bm.get_pos(enemy)
            if not pos:
                continue
            r = CELL // 2 - 3
            el = QGraphicsEllipseItem(-r, -r, 2 * r, 2 * r)
            el.setPos(pos[0] * CELL + CELL // 2, pos[1] * CELL + CELL // 2)
            el.setBrush(QBrush(color if enemy.alive else QColor('#555555')))
            el.setPen(QPen(QColor('black'), 1))
            el.setData(0, enemy)            # токен несёт своё существо
            scene.addItem(el)
            txt = scene.addSimpleText(enemy.name.split('_')[-1][:2], font)
            txt.setParentItem(el)
            txt.setBrush(QBrush(QColor('white')))
            tb = txt.boundingRect()
            txt.setPos(-tb.width() / 2, -tb.height() / 2)
    return scene


def build_demo():
    bm = BattleMap(width=24, height=16)
    comp = [('гоблин', 10), ('орк', 8), ('скелет', 8)]
    sides = [[EnemyFactory.create_enemy(t, f'Сторона {chr(65 + i)}_{j + 1}', i)
              for j in range(n)] for i, (t, n) in enumerate(comp)]
    bm.formation_placement(sides)
    return bm, sides


def main():
    app = QApplication(sys.argv)
    bm, sides = build_demo()
    scene = build_scene(bm, sides)
    info = QLabel('Клик по токену - данные существа; колесо - зум; '
                  'тяни пустое место - панорама.')
    info.setStyleSheet('padding: 6px;')

    def on_pick(enemy):
        info.setText(f'{enemy.name}: HP {enemy.hp}/{enemy.max_hp}, AC {enemy.ac}, '
                     f'клетка {bm.get_pos(enemy)}, атак: {len(enemy.attacks)}')

    view = MapView(scene, on_pick)
    win = QWidget()
    lay = QVBoxLayout(win)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(view, 1)
    lay.addWidget(info, 0)
    win.resize(900, 640)
    win.setWindowTitle('Qt-спайк: карта боя на QGraphicsView')
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()