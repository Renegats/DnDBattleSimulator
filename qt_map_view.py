"""Карта боя на QGraphicsView: фон, зум, панорама, токены по размеру существ.

Токен занимает столько клеток, сколько указано в статблоке: крошечный — четверть
клетки, большой — 2×2, огромный — 3×3, громадный — 4×4. Подсветка досягаемости
строится по пятну, а не по одной клетке.
"""
import math
import os

from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QPointF
from PyQt6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath,
                          QPen, QPixmap, QPolygonF, QRadialGradient)
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
    'attack_lines': True,
}

# Стиль отрезка атаки: цвет, толщина, штрих. Координаты приходят в клетках.
ATTACK_STYLES = {
    'hit': ('#e74c3c', 2.6, Qt.PenStyle.SolidLine),
    'crit': ('#f1c40f', 3.8, Qt.PenStyle.SolidLine),
    'miss': ('#95a5a6', 1.8, Qt.PenStyle.DashLine),
    'nat1': ('#9b59b6', 2.0, Qt.PenStyle.DotLine),
    'heal': ('#2ecc71', 2.6, Qt.PenStyle.SolidLine),
    'move': ('#3498db', 1.8, Qt.PenStyle.DashDotLine),
}


_TERRAIN_DARK = {
    'wall': ((74, 81, 96, 235), (186, 194, 206)),
    'difficult': ((138, 154, 74, 110), (214, 224, 150)),
    'water': ((46, 134, 171, 150), (214, 243, 255)),
    'half': ((224, 179, 65, 120), (255, 224, 138)),
    'three_quarters': ((224, 122, 61, 150), (255, 214, 186)),
    'total': ((142, 61, 85, 170), (255, 208, 220)),
}
_TERRAIN_LIGHT = {
    'wall': ((110, 101, 88, 230), (62, 56, 47)),
    'difficult': ((109, 122, 50, 120), (63, 74, 24)),
    'water': ((61, 142, 184, 140), (8, 54, 74)),
    'half': ((196, 146, 42, 130), (106, 74, 8)),
    'three_quarters': ((198, 90, 30, 140), (90, 36, 8)),
    'total': ((138, 48, 72, 150), (58, 16, 32)),
}

COVER_TINT = {
    'none': (46, 204, 113, 90),
    'half': (241, 196, 15, 110),
    'three_quarters': (230, 126, 34, 120),
    'total': (231, 76, 60, 130),
}


class MapView(QGraphicsView):
    token_clicked = pyqtSignal(object)
    token_menu = pyqtSignal(object, object)
    cell_menu = pyqtSignal(float, float, object)
    cell_clicked = pyqtSignal(float, float)
    token_dragged = pyqtSignal(object, float, float)
    image_dropped = pyqtSignal(str)
    aim_moved = pyqtSignal(float, float)
    terrain_cell = pyqtSignal(int, int, bool)
    terrain_stroke_finished = pyqtSignal()
    hover_target = pyqtSignal(object)

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
        self._token_drag = None
        self._token_press = None
        self._token_moved = False
        self._bm = None
        self._sides = []
        self._selected = None
        self._bg_path = None
        self._bg_pix = None
        self._bg_cache = {}
        self._round_lines = []
        self._focus_lines = []
        self._focus_enemies = []
        self._attack_items = []
        self._focus_items = []
        self._area_cells = []
        self._preview_cells = []
        self._focus_cells = []
        self._area_items = []
        self._aiming = False
        self._terrain_mode = False
        self._terrain_stroke = None
        self._terrain_items = []
        self._cover_enemy = None
        self._cover_kind = None
        self._cover_items = []
        self._hover_enemy = None
        self._cover_hover = False

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
        if key == 'attack_lines':
            self._paint_attack_lines()
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

    def _token_at(self, pos):
        it = self.itemAt(pos)
        while it is not None and it.data(0) is None and it.parentItem() is not None:
            it = it.parentItem()
        if it is not None and it.data(0) is not None:
            return it.data(0)
        return None

    @staticmethod
    def _cell_at(scene_pos, cell):
        return (round(scene_pos.x() / cell * 2) / 2,
                round(scene_pos.y() / cell * 2) / 2)

    def mousePressEvent(self, e):
        if self._terrain_mode and not self._aiming and e.button() in (
                Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            cell = self._cell_floor(e.pos())
            if cell is not None:
                erase = e.button() == Qt.MouseButton.RightButton
                self._terrain_stroke = erase
                self.terrain_cell.emit(cell[0], cell[1], erase)
            e.accept()
            return
        if e.button() == Qt.MouseButton.RightButton:
            point = e.globalPosition().toPoint()
            enemy = self._token_at(e.pos())
            if enemy is not None:
                self.token_menu.emit(enemy, point)
            elif not self._aiming:
                sp = self.mapToScene(e.pos())
                x, y = self._cell_at(sp, self.opts['cell'])
                self.cell_menu.emit(x, y, point)
            e.accept()
            return
        if e.button() == Qt.MouseButton.LeftButton:
            enemy = self._token_at(e.pos())
            if enemy is not None and not self._aiming:
                self._token_drag = enemy
                self._token_press = e.pos()
                self._token_moved = False
                self.token_clicked.emit(enemy)
                e.accept()
                return
            if enemy is not None and self._aiming:
                self.token_clicked.emit(enemy)
                e.accept()
                return
            self._press = e.pos()
            self._last = e.pos()
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(e)

    def set_aiming(self, on):
        """Клик и движение мыши выбирают клетку прицела, а не тащат карту."""
        self._aiming = bool(on)
        self._track_mouse()
        if not on and not self._terrain_mode:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_terrain_mode(self, on):
        """Кисть рельефа: левая кнопка рисует, правая стирает, протягивание — штрих."""
        self._terrain_mode = bool(on)
        self._terrain_stroke = None
        self._track_mouse()
        if on:
            self.setCursor(Qt.CursorShape.CrossCursor)
        elif not self._aiming:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def set_cover_hover(self, on):
        self._cover_hover = bool(on)
        self._track_mouse()
        if not on:
            self._hover_enemy = None

    def _track_mouse(self):
        self.setMouseTracking(self._aiming or self._terrain_mode or self._cover_hover)

    def set_cover_overlay(self, enemy, kind):
        self._cover_enemy = enemy
        self._cover_kind = kind
        self._paint_cover()

    def _cell_floor(self, pos):
        sp = self.mapToScene(pos)
        cell = self.opts['cell']
        if cell <= 0:
            return None
        return int(math.floor(sp.x() / cell)), int(math.floor(sp.y() / cell))

    def _map_is_dark(self):
        return QColor(self.pal.get('canvas_map', '#2b2d31')).lightness() < 140

    def mouseMoveEvent(self, e):
        if self._terrain_stroke is not None:
            cell = self._cell_floor(e.pos())
            if cell is not None:
                self.terrain_cell.emit(cell[0], cell[1], bool(self._terrain_stroke))
            e.accept()
            return
        if self._cover_hover or self._aiming:
            enemy = self._token_at(e.pos())
            if enemy is not self._hover_enemy:
                self._hover_enemy = enemy
                self.hover_target.emit(enemy)
        if self._aiming and self._token_drag is None:
            sp = self.mapToScene(e.pos())
            x, y = self._cell_at(sp, self.opts['cell'])
            self.aim_moved.emit(x, y)
            if self._press is not None:
                e.accept()
                return
        if self._token_drag is not None and self._token_press is not None:
            if (e.pos() - self._token_press).manhattanLength() > 6:
                self._token_moved = True
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            e.accept()
            return
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
        if self._terrain_stroke is not None:
            self._terrain_stroke = None
            self.terrain_stroke_finished.emit()
            e.accept()
            return
        if self._token_drag is not None:
            enemy = self._token_drag
            moved = self._token_moved
            press = self._token_press
            self._token_drag = None
            self._token_press = None
            self._token_moved = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if moved and press is not None:
                sp = self.mapToScene(e.pos())
                x, y = self._cell_at(sp, self.opts['cell'])
                self.token_dragged.emit(enemy, x, y)
            e.accept()
            return
        if self._press is not None:
            if self._aiming or not self._dragged:
                sp = self.mapToScene(e.pos() if self._aiming else self._press)
                x, y = self._cell_at(sp, self.opts['cell'])
                self.cell_clicked.emit(x, y)
            self._press = None
            if not self._aiming:
                self.setCursor(Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(e)

    # ---------- отрисовка ----------
    def _reach_cells(self, bm, enemy, c):
        del c
        return bm.reach_half_cells(enemy)

    def set_area_cells(self, cells):
        """Клетки уже сыгранной области. Сцену не пересобирает."""
        self._area_cells = [tuple(cell) for cell in cells or []]
        self._paint_areas()

    def set_preview_cells(self, cells):
        """Живой прицел: клетки, которые накроет выбранное направление."""
        self._preview_cells = [tuple(cell) for cell in cells or []]
        self._paint_areas()

    def set_focus_areas(self, cells):
        """Клетки одной записи журнала поверх области раунда."""
        self._focus_cells = [tuple(cell) for cell in cells or []]
        self._paint_areas()

    def set_round_lines(self, lines):
        """Линии последнего раунда. Снимает прежние стрелки, сцену не чистит."""
        self._round_lines = list(lines or [])
        self._focus_lines = []
        self._focus_enemies = []
        self._paint_attack_lines()
        self._paint_focus_rings()

    def set_focus_lines(self, lines):
        """Подсветка одной записи поверх линий раунда, без пересборки сцены."""
        self._focus_lines = list(lines or [])
        self._paint_attack_lines()

    def focus_creatures(self, enemies):
        """Кольца вокруг существ и центр кадра. Токены не перерисовываются."""
        self._focus_enemies = [enemy for enemy in enemies if enemy is not None]
        self._paint_focus_rings()
        if self._bm is None or not self._focus_enemies:
            return
        rect = None
        cell = self.opts['cell']
        for enemy in self._focus_enemies:
            pos = self._bm.get_pos(enemy)
            if not pos:
                continue
            side = self._bm.cells_of(enemy) * cell
            piece = QRectF(pos[0] * cell, pos[1] * cell, side, side)
            rect = piece if rect is None else rect.united(piece)
        if rect is None:
            return
        margin = cell * 1.5
        self.ensureVisible(rect.adjusted(-margin, -margin, margin, margin), 20, 20)
        self.centerOn(rect.center())

    def _paint_attack_lines(self):
        scene = self.scene()
        for item in self._attack_items:
            scene.removeItem(item)
        self._attack_items = []
        if not self.opts.get('attack_lines', True) or self._bm is None:
            return
        dim = bool(self._focus_lines)
        for spec in self._round_lines:
            self._add_attack_line(spec, 0.35 if dim else 0.95, 1.0)
        for spec in self._focus_lines:
            self._add_attack_line(spec, 1.0, 1.45)

    def _add_attack_line(self, spec, opacity, width_scale):
        cell = self.opts['cell']
        r1 = float(spec.get('r1') or 0.45)
        r2 = float(spec.get('r2') or 0.45)
        x1 = (float(spec['x1']) + r1) * cell
        y1 = (float(spec['y1']) + r1) * cell
        x2 = (float(spec['x2']) + r2) * cell
        y2 = (float(spec['y2']) + r2) * cell
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 2:
            return
        ux, uy = dx / length, dy / length
        pad1, pad2 = r1 * cell * 0.92, r2 * cell * 0.92
        if length <= pad1 + pad2 + 4:
            pad1 = pad2 = 0
        sx, sy = x1 + ux * pad1, y1 + uy * pad1
        ex, ey = x2 - ux * pad2, y2 - uy * pad2
        color_hex, width, pen_style = ATTACK_STYLES.get(spec.get('style'), ATTACK_STYLES['hit'])
        color = QColor(color_hex)
        pen = QPen(color, max(1.0, width * width_scale), pen_style)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        line = self.scene().addLine(sx, sy, ex, ey, pen)
        line.setOpacity(opacity)
        line.setZValue(6)
        line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._attack_items.append(line)
        head = 11 * width_scale
        spread = 4.5 * width_scale
        polygon = QPolygonF([
            QPointF(ex, ey),
            QPointF(ex - ux * head - uy * spread, ey - uy * head + ux * spread),
            QPointF(ex - ux * head + uy * spread, ey - uy * head - ux * spread),
        ])
        arrow = self.scene().addPolygon(polygon, QPen(Qt.PenStyle.NoPen), QBrush(color))
        arrow.setOpacity(opacity)
        arrow.setZValue(6)
        arrow.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._attack_items.append(arrow)

    def _paint_focus_rings(self):
        scene = self.scene()
        for item in self._focus_items:
            scene.removeItem(item)
        self._focus_items = []
        if self._bm is None:
            return
        cell = self.opts['cell']
        pen = QPen(QColor('#f1c40f'), 3)
        pen.setCosmetic(True)
        for enemy in self._focus_enemies:
            pos = self._bm.get_pos(enemy)
            if not pos:
                continue
            side = self._bm.cells_of(enemy) * cell
            pad = max(2, side * 0.08)
            ring = scene.addEllipse(
                pos[0] * cell - pad, pos[1] * cell - pad, side + 2 * pad, side + 2 * pad,
                pen, QBrush(Qt.BrushStyle.NoBrush))
            ring.setZValue(7)
            ring.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            self._focus_items.append(ring)

    def _paint_areas(self):
        scene = self.scene()
        for item in self._area_items:
            scene.removeItem(item)
        self._area_items = []
        if self._bm is None:
            return
        cell = self.opts['cell']
        layers = (
            (self._area_cells, QColor(230, 126, 34, 110), QColor(192, 86, 12, 180), -1),
            (self._preview_cells, QColor(241, 196, 15, 150), QColor(241, 196, 15, 230), 0),
            (self._focus_cells, QColor(241, 196, 15, 80), QColor(255, 230, 120, 240), 5),
        )
        for cells, fill, edge, z_value in layers:
            pen = QPen(edge, 1.4)
            pen.setCosmetic(True)
            brush = QBrush(fill)
            for cx, cy in cells:
                try:
                    left, top = float(cx) * cell, float(cy) * cell
                except (TypeError, ValueError):
                    continue
                rect = scene.addRect(left + 1, top + 1, cell - 2, cell - 2, pen, brush)
                rect.setZValue(z_value)
                rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
                self._area_items.append(rect)

    def rebuild(self, bm, sides, selected=None):
        lines = list(self._round_lines)
        focus_lines = list(self._focus_lines)
        focus_enemies = [enemy for enemy in self._focus_enemies if enemy is not None]
        area_cells = list(self._area_cells)
        preview_cells = list(self._preview_cells)
        focus_cells = list(self._focus_cells)
        self._attack_items = []
        self._focus_items = []
        self._area_items = []
        self._terrain_items = []
        self._cover_items = []
        self._bm, self._sides, self._selected = bm, sides or [], selected
        sc = self.scene()
        sc.clear()
        self.setBackgroundBrush(QColor(self.pal['canvas_map']))
        self._round_lines = lines
        self._focus_lines = focus_lines
        self._focus_enemies = focus_enemies
        self._area_cells = area_cells
        self._preview_cells = preview_cells
        self._focus_cells = focus_cells
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

        self._paint_terrain()

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
                    path = QPainterPath()
                    radius = max(3.0, box * 0.14)
                    path.addRoundedRect(QRectF(x0, y0, box, box), radius, radius)
                    item = sc.addPath(path, pen, fill)
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
                self._paint_condition_badges(item, en, x0, y0, box)
        self._paint_areas()
        self._paint_attack_lines()
        self._paint_focus_rings()
        self._paint_cover()

    def refresh_terrain(self):
        """Перерисовать только клетки рельефа, не трогая токены."""
        if self._bm is None:
            return
        self._paint_terrain()
        self._paint_cover()

    def _remember(self, item):
        item.setZValue(-4)
        item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._terrain_items.append(item)
        return item

    def _paint_terrain(self):
        scene = self.scene()
        for item in self._terrain_items:
            scene.removeItem(item)
        self._terrain_items = []
        bm = self._bm
        if bm is None or not bm.has_terrain():
            return
        cell = self.opts['cell']
        palette = _TERRAIN_DARK if self._map_is_dark() else _TERRAIN_LIGHT
        for (x, y), kind in bm._terrain.items():
            fill, edge = palette.get(kind, palette['wall'])
            left, top = x * cell, y * cell
            rect = scene.addRect(
                left + 1, top + 1, cell - 2, cell - 2,
                QPen(QColor(*edge), 1.2), QBrush(QColor(*fill)))
            self._remember(rect)
            self._terrain_mark(scene, kind, left, top, cell, QColor(*edge))

    def _terrain_mark(self, scene, kind, left, top, cell, color):
        pen = QPen(color, 1.4)
        pen.setCosmetic(True)
        inset = max(3, cell * 0.18)

        def line(x1, y1, x2, y2):
            item = scene.addLine(x1, y1, x2, y2, pen)
            self._remember(item)

        if kind == 'wall':
            line(left + inset, top + cell * 0.38, left + cell - inset, top + cell * 0.38)
            line(left + inset, top + cell * 0.62, left + cell - inset, top + cell * 0.62)
            line(left + cell * 0.35, top + inset, left + cell * 0.35, top + cell * 0.38)
            line(left + cell * 0.68, top + cell * 0.38, left + cell * 0.68, top + cell * 0.62)
        elif kind == 'difficult':
            for step in (0.25, 0.5, 0.75):
                line(left + cell * step, top + inset, left + inset, top + cell * step)
                line(left + cell - inset, top + cell * step, left + cell * step, top + cell - inset)
        elif kind == 'water':
            for frac in (0.32, 0.5, 0.68):
                y = top + cell * frac
                line(left + inset, y, left + cell * 0.35, y - cell * 0.06)
                line(left + cell * 0.35, y - cell * 0.06, left + cell * 0.65, y + cell * 0.06)
                line(left + cell * 0.65, y + cell * 0.06, left + cell - inset, y)
        elif kind == 'half':
            block = scene.addRect(
                left + inset, top + cell * 0.55, cell - 2 * inset, cell * 0.28,
                QPen(Qt.PenStyle.NoPen), QBrush(color))
            self._remember(block)
        elif kind == 'three_quarters':
            thick = max(3.0, cell * 0.16)
            for rect in (
                (left + inset, top + inset, cell - 2 * inset, thick),
                (left + inset, top + inset, thick, cell - 2 * inset),
                (left + cell - inset - thick, top + inset, thick, cell - 2 * inset),
            ):
                block = scene.addRect(*rect, QPen(Qt.PenStyle.NoPen), QBrush(color))
                self._remember(block)
        elif kind == 'total':
            line(left + inset, top + inset, left + cell - inset, top + cell - inset)
            line(left + cell - inset, top + inset, left + inset, top + cell - inset)

    def _paint_cover(self):
        scene = self.scene()
        for item in self._cover_items:
            scene.removeItem(item)
        self._cover_items = []
        enemy = self._cover_enemy
        bm = self._bm
        if enemy is None or bm is None or self._cover_kind is None:
            return
        pos = bm.get_pos(enemy)
        if not pos:
            return
        cell = self.opts['cell']
        tint = COVER_TINT.get(self._cover_kind, COVER_TINT['none'])
        side = bm.cells_of(enemy) * cell
        pen = QPen(QColor(tint[0], tint[1], tint[2]), 2.4)
        pen.setCosmetic(True)
        rect = scene.addRect(
            pos[0] * cell, pos[1] * cell, side, side, pen,
            QBrush(QColor(*tint)))
        rect.setZValue(5)
        rect.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self._cover_items.append(rect)

    def _paint_condition_badges(self, item, enemy, x0, y0, box):
        from conditions import (active_conditions, condition_color, condition_short,
                                condition_tooltip)
        item.setToolTip(condition_tooltip(enemy))
        badges = [cond for cond in active_conditions(enemy) if isinstance(cond, dict)]
        if not badges:
            return
        font = QFont('Arial', max(6, int(min(11, box * 0.2))), QFont.Weight.Bold)
        gap = max(1.0, box * 0.04)
        badge_w = max(16.0, min(box * 0.36, 30.0))
        badge_h = max(11.0, min(box * 0.24, 16.0))
        total = len(badges) * badge_w + max(0, len(badges) - 1) * gap
        left = x0 + max(0.0, (box - total) / 2)
        top = y0 + box - badge_h - 1
        for index, cond in enumerate(badges[:6]):
            color = QColor(condition_color(cond.get('id')))
            badge = self.scene().addRect(
                left + index * (badge_w + gap), top, badge_w, badge_h,
                QPen(QColor('#ffffff'), 0.6), QBrush(color))
            badge.setParentItem(item)
            badge.setZValue(3)
            label = self.scene().addSimpleText(
                condition_short(cond.get('id'), cond.get('level')), font)
            label.setParentItem(item)
            label.setBrush(QBrush(QColor('#ffffff')))
            bounds = label.boundingRect()
            label.setPos(left + index * (badge_w + gap) + (badge_w - bounds.width()) / 2,
                         top + (badge_h - bounds.height()) / 2)
            label.setZValue(4)