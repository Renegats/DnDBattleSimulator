"""Карта боя на QGraphicsView: фон, зум, панорама, токены по размеру существ.

Токен занимает столько клеток, сколько указано в статблоке: крошечный — четверть
клетки, большой — 2×2, огромный — 3×3, громадный — 4×4. Подсветка досягаемости
строится по пятну, а не по одной клетке.
"""
import os

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import (QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsRectItem,
                             QGraphicsScene, QGraphicsView)

CELL = 28

SIDE_PALETTES = {
    'classic': ['#e74c3c', '#3498db', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22'],
    'neon':    ['#ff2e63', '#08d9d6', '#a6ff00', '#ff9f1c', '#b14aed', '#ff5d8f'],
    'parchment': ['#a83232', '#2f5d8a', '#4a7c3f', '#b8860b', '#6b4a8a', '#c0662a'],
}

BG_MODES = ['stretch', 'fit', 'cover', 'tile']
IMAGE_EXT = ('.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif', '.tif', '.tiff')

DEFAULT_OPTS = {
    'cell': 28, 'zoom': 100, 'grid': True, 'reach': True,
    'labels': 'number', 'dead_alpha': 45, 'stroke': 1,
    'glow': True, 'sides': 'classic',
    'bg_opacity': 100, 'bg_mode': 'stretch',
}


class MapView(QGraphicsView):
    token_clicked = pyqtSignal(object)
    cell_clicked = pyqtSignal(float, float)
    image_dropped = pyqtSignal(str)

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.pal = palette
        self.opts = dict(DEFAULT_OPTS)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMinimumHeight(240)
        self.setAcceptDrops(True)
        self._press = None
        self._last = None
        self._dragged = False
        self._bm = None
        self._sides = []
        self._selected = None
        self._bg_path = None
        self._bg_pix = None
        self._bg_cache = {}

    # ---------- фон ----------
    def set_background(self, path):
        pix = QPixmap(path)
        if pix.isNull():
            return False
        self._bg_path, self._bg_pix = path, pix
        self._bg_cache.clear()
        self.rebuild(self._bm, self._sides, self._selected)
        return True

    def clear_background(self):
        self._bg_path = self._bg_pix = None
        self._bg_cache.clear()
        self.rebuild(self._bm, self._sides, self._selected)

    @property
    def background_path(self):
        return self._bg_path

    def background_info(self):
        if self._bg_pix is None or self._bg_pix.isNull():
            return None
        return (os.path.basename(self._bg_path or 'изображение'),
                self._bg_pix.width(), self._bg_pix.height())

    def _scaled_bg(self, w, h, mode):
        W, H = max(1, int(w)), max(1, int(h))
        key = (W, H, mode)
        hit = self._bg_cache.get(key)
        if hit is not None:
            return hit
        aspect = {'stretch': Qt.AspectRatioMode.IgnoreAspectRatio,
                  'fit': Qt.AspectRatioMode.KeepAspectRatio,
                  'cover': Qt.AspectRatioMode.KeepAspectRatioByExpanding}[mode]
        pix = self._bg_pix.scaled(W, H, aspect, Qt.TransformationMode.SmoothTransformation)
        if mode == 'cover':
            cx = max(0, (pix.width() - W) // 2)
            cy = max(0, (pix.height() - H) // 2)
            pix = pix.copy(cx, cy, min(W, pix.width()), min(H, pix.height()))
        if len(self._bg_cache) > 12:
            self._bg_cache.clear()
        self._bg_cache[key] = pix
        return pix

    def _draw_background(self, sc, w, h):
        if self._bg_pix is None or self._bg_pix.isNull():
            return
        mode = self.opts['bg_mode']
        op = max(0.05, min(1.0, self.opts['bg_opacity'] / 100.0))
        if mode == 'tile':
            tile = QGraphicsRectItem(0, 0, w, h)
            tile.setBrush(QBrush(self._bg_pix))
            tile.setPen(QPen(Qt.PenStyle.NoPen))
            tile.setOpacity(op)
            tile.setZValue(-10)
            sc.addItem(tile)
            return
        pix = self._scaled_bg(w, h, mode)
        item = QGraphicsPixmapItem(pix)
        item.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        item.setOpacity(op)
        item.setZValue(-10)
        item.setPos(0 if mode == 'stretch' else (w - pix.width()) / 2.0,
                    0 if mode == 'stretch' else (h - pix.height()) / 2.0)
        sc.addItem(item)

    # ---------- drag & drop ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                if u.toLocalFile().lower().endswith(IMAGE_EXT):
                    e.acceptProposedAction()
                    return
        super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            return
        super().dragMoveEvent(e)

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            path = u.toLocalFile()
            if path.lower().endswith(IMAGE_EXT):
                self.image_dropped.emit(path)
                e.acceptProposedAction()
                return
        super().dropEvent(e)

    # ---------- настройки ----------
    def set_opt(self, key, value):
        self.opts[key] = value
        if key == 'zoom':
            self.resetTransform()
            f = max(10, value) / 100.0
            self.scale(f, f)
            return
        self.rebuild(self._bm, self._sides, self._selected)

    def reset_opts(self):
        self.opts = dict(DEFAULT_OPTS)
        self.resetTransform()
        self.rebuild(self._bm, self._sides, self._selected)

    def set_palette(self, palette):
        self.pal = palette
        self.rebuild(self._bm, self._sides, self._selected)

    def export_png(self, path):
        rect = self.scene().sceneRect()
        if rect.isEmpty():
            rect = QRectF(0, 0, 400, 300)
        img = QImage(max(1, int(rect.width())), max(1, int(rect.height())),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QColor(self.pal['canvas_map']))
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.scene().render(p, QRectF(img.rect()), rect)
        p.end()
        return img.save(path)

    # ---------- навигация ----------
    def wheelEvent(self, e):
        step = 10 if e.angleDelta().y() > 0 else -10
        self.opts['zoom'] = max(25, min(300, self.opts['zoom'] + step))
        self.resetTransform()
        f = self.opts['zoom'] / 100.0
        self.scale(f, f)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            it = self.itemAt(e.pos())
            while it is not None and it.data(0) is None and it.parentItem() is not None:
                it = it.parentItem()
            if it is not None and it.data(0) is not None:
                self.token_clicked.emit(it.data(0))
                return
            self._press = e.pos()
            self._last = e.pos()
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None:
            if (e.pos() - self._press).manhattanLength() > 4:
                self._dragged = True
            if self._dragged:
                d = e.pos() - self._last
                self._last = e.pos()
                self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - d.x())
                self.verticalScrollBar().setValue(self.verticalScrollBar().value() - d.y())
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._press is not None:
            if not self._dragged:
                sp = self.mapToScene(self._press)
                c = self.opts['cell']
                self.cell_clicked.emit(round(sp.x() / c * 2) / 2,
                                       round(sp.y() / c * 2) / 2)
            self._press = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(e)

    # ---------- отрисовка ----------
    def _reach_cells(self, bm, enemy, c):
        pos = bm.get_pos(enemy)
        if not pos:
            return set()
        n = bm.span_of(enemy)
        step = 1 if n == 1 else 2
        left = max(0, enemy.speed - getattr(enemy, 'moved_ft', 0))
        radius_h = int(left // 2.5)
        ax, ay = int(round(pos[0] * 2)), int(round(pos[1] * 2))
        covered = set()
        for dy in range(-radius_h, radius_h + 1, step):
            for dx in range(-radius_h, radius_h + 1, step):
                hx, hy = ax + dx, ay + dy
                if not bm._area_free(hx, hy, n, ignore_id=id(enemy)):
                    continue
                for yy in range(hy, hy + n):
                    for xx in range(hx, hx + n):
                        covered.add((xx, yy))
        return covered

    def rebuild(self, bm, sides, selected=None):
        self._bm, self._sides, self._selected = bm, sides or [], selected
        sc = self.scene()
        sc.clear()
        self.setBackgroundBrush(QColor(self.pal['canvas_map']))
        if bm is None:
            return
        o = self.opts
        c = o['cell']
        w, h = bm.width * c, bm.height * c
        sc.setSceneRect(0, 0, w, h)
        self._draw_background(sc, w, h)

        if o['grid']:
            gc = QColor(self.pal['canvas_grid'])
            if self._bg_pix is not None:
                gc.setAlpha(150)
            gp = QPen(gc, 1)
            for x in range(bm.width + 1):
                sc.addLine(x * c, 0, x * c, h, gp).setZValue(-5)
            for y in range(bm.height + 1):
                sc.addLine(0, y * c, w, y * c, gp).setZValue(-5)
            half = QColor(gc)
            half.setAlpha(70)
            hp = QPen(half, 1, Qt.PenStyle.DotLine)
            for x in range(bm.width):
                sc.addLine(x * c + c / 2, 0, x * c + c / 2, h, hp).setZValue(-6)
            for y in range(bm.height):
                sc.addLine(0, y * c + c / 2, w, y * c + c / 2, hp).setZValue(-6)

        if o['reach'] and selected is not None and selected.alive:
            brush = QBrush(QColor(self.pal['canvas_reach']))
            alpha = 0.5 if self._bg_pix is not None else 1.0
            for hx, hy in self._reach_cells(bm, selected, c):
                r = sc.addRect(hx * c / 2 + 1, hy * c / 2 + 1, c / 2 - 2, c / 2 - 2,
                               QPen(Qt.PenStyle.NoPen), brush)
                r.setOpacity(alpha)
                r.setZValue(-2)

        colors = SIDE_PALETTES[o['sides']]
        no_pen = QPen(Qt.PenStyle.NoPen)
        for i, side in enumerate(self._sides):
            color = QColor(colors[i % len(colors)])
            for en in sorted(side, key=lambda e: (e.alive, bm.cells_of(e))):
                pos = bm.get_pos(en)
                if not pos:
                    continue
                cells = bm.cells_of(en)
                side_px = cells * c
                pad = max(1.5, side_px * 0.09)
                x0, y0 = pos[0] * c + pad, pos[1] * c + pad
                box = side_px - 2 * pad
                cx, cy = pos[0] * c + side_px / 2, pos[1] * c + side_px / 2
                is_sel = en is selected

                if is_sel and o['glow']:
                    R = side_px * 0.95
                    grad = QRadialGradient(cx, cy, R)
                    hot = QColor(self.pal['accent']); hot.setAlpha(165)
                    mid = QColor(self.pal['accent']); mid.setAlpha(80)
                    cold = QColor(self.pal['accent']); cold.setAlpha(0)
                    grad.setColorAt(0.0, hot)
                    grad.setColorAt(0.45, mid)
                    grad.setColorAt(1.0, cold)
                    halo = sc.addEllipse(cx - R, cy - R, 2 * R, 2 * R, no_pen, QBrush(grad))
                    halo.setZValue(1)

                fill = QBrush(color if en.alive else QColor('#555555'))
                pen = QPen(QColor('#ffffff' if is_sel else '#000000'),
                           max(1, o['stroke'] + (1 if is_sel else 0)))
                if cells >= 2:
                    item = sc.addRoundedRect(x0, y0, box, box,
                                             max(3.0, box * 0.14), max(3.0, box * 0.14),
                                             pen, fill)
                else:
                    item = sc.addEllipse(x0, y0, box, box, pen, fill)
                if not en.alive:
                    item.setOpacity(max(0.1, o['dead_alpha'] / 100.0))
                item.setData(0, en)
                item.setZValue(2 + cells * 0.01)

                if o['labels'] != 'none':
                    txt = (en.name.split('_')[0][:6] if o['labels'] == 'name'
                           else en.name.split('_')[-1][:3])
                    font = QFont('Arial', max(6, int(min(20, box * 0.34))), QFont.Weight.Bold)
                    t = sc.addSimpleText(txt, font)
                    t.setParentItem(item)
                    t.setBrush(QBrush(QColor('#ffffff')))
                    b = t.boundingRect()
                    t.setPos(x0 + (box - b.width()) / 2, y0 + (box - b.height()) / 2)
                    if not en.alive:
                        t.setOpacity(max(0.1, o['dead_alpha'] / 100.0))