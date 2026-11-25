"""Векторные кнопки-иконки и карточка отряда с автоматическим портретом.

Карточка не имеет ручек кадрирования: qt_portrait сам выбирает композицию.
Полоса рендерится в devicePixelRatio (резко на HiDPI) и кэшируется.
"""
import math

from PyQt6.QtCore import Qt, QSize, QRectF, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath, QPolygonF
from PyQt6.QtWidgets import QAbstractButton, QFrame

from qt_portrait import band_height, render_band


class IconButton(QAbstractButton):
    """kind: 'moon' | 'sun' | 'plus' | 'cross' | 'swap' | 'dice' | 'image'."""

    def __init__(self, kind, palette, size=38, outline=False, round_shape=False, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.pal = palette
        self._outline = outline
        self._round = round_shape
        self._d = size
        self._hover = False
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def sizeHint(self):
        return QSize(self._d, self._d)

    def set_palette(self, palette):
        self.pal = palette
        self.update()

    def set_kind(self, kind):
        self.kind = kind
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        w, h = self.width(), self.height()
        pal = self.pal
        active = self._hover or self.isDown() or self.isChecked()
        body = QRectF(1.0, 1.0, w - 2.0, h - 2.0)
        radius = (min(w, h) - 2) / 2.0 if self._round else 9.0
        if self.isChecked():
            fill = QColor(pal['accent'])
        elif self._outline:
            fill = QColor(pal['bg_secondary'] if self._hover else pal['bg'])
        else:
            fill = QColor(pal['hover'] if active else pal['button_bg'])
        p.setPen(QPen(QColor(pal['accent'] if active else pal['border']), 1.4))
        p.setBrush(QBrush(fill))
        p.drawRoundedRect(body, radius, radius)
        self._draw_icon(p, w / 2.0, h / 2.0, max(3.0, min(w, h) / 2.0 - 8.0))
        p.end()

    def _draw_icon(self, p, cx, cy, r):
        pal = self.pal
        hot = self._hover or self.isChecked()
        if self.kind == 'moon':
            outer = QPainterPath()
            outer.addEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
            bite = QPainterPath()
            bite.addEllipse(QRectF(cx - r + 0.62 * r, cy - r - 0.30 * r, 2 * r, 2 * r))
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(outer.subtracted(bite), QColor('#f5d76e'))
        elif self.kind == 'sun':
            col = QColor('#e8a33d')
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(cx, cy), r * 0.52, r * 0.52)
            p.setPen(QPen(col, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for i in range(8):
                a = i * math.pi / 4.0
                p.drawLine(QPointF(cx + math.cos(a) * r * 0.74, cy + math.sin(a) * r * 0.74),
                           QPointF(cx + math.cos(a) * r, cy + math.sin(a) * r))
        elif self.kind == 'plus':
            col = QColor(pal['accent'] if hot else pal['fg_muted'])
            p.setPen(QPen(col, 1.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r, r)
            arm = r * 0.52
            p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
            p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
        elif self.kind == 'cross':
            col = QColor(pal['danger'] if self._hover else pal['fg_muted'])
            p.setPen(QPen(col, 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            arm = r * 0.55
            p.drawLine(QPointF(cx - arm, cy - arm), QPointF(cx + arm, cy + arm))
            p.drawLine(QPointF(cx + arm, cy - arm), QPointF(cx - arm, cy + arm))
        elif self.kind == 'swap':
            col = QColor(pal['accent'] if self._hover else pal['fg_muted'])
            p.setPen(QPen(col, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(cx - r * 0.78, cy - r * 0.78, r * 1.56, r * 1.56)
            p.drawArc(box, 25 * 16, 130 * 16)
            p.drawArc(box, 205 * 16, 130 * 16)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            for ang, direction in ((25, 1), (205, -1)):
                a = math.radians(ang)
                tip = QPointF(cx + math.cos(a) * r * 0.78, cy - math.sin(a) * r * 0.78)
                t = QPointF(-math.sin(a) * direction, -math.cos(a) * direction)
                n = QPointF(math.cos(a), -math.sin(a))
                s = r * 0.30
                p.drawPolygon(QPolygonF([tip + t * s,
                                         tip - t * s * 0.35 + n * s * 0.55,
                                         tip - t * s * 0.35 - n * s * 0.55]))
        elif self.kind == 'dice':
            col = QColor(pal['accent'] if hot else pal['fg_muted'])
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(cx - r * 0.82, cy - r * 0.82, r * 1.64, r * 1.64)
            p.drawRoundedRect(box, r * 0.3, r * 0.3)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            d, pr = r * 0.42, max(1.1, r * 0.13)
            for dx, dy in ((-d, -d), (d, -d), (0, 0), (-d, d), (d, d)):
                p.drawEllipse(QPointF(cx + dx, cy + dy), pr, pr)
        elif self.kind == 'image':
            col = QColor(pal['accent'] if hot else pal['fg_muted'])
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(cx - r * 0.85, cy - r * 0.7, r * 1.7, r * 1.4),
                              r * 0.22, r * 0.22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(cx - r * 0.38, cy - r * 0.26), r * 0.16, r * 0.16)
            p.drawPolygon(QPolygonF([
                QPointF(cx - r * 0.72, cy + r * 0.52),
                QPointF(cx - r * 0.12, cy - r * 0.12),
                QPointF(cx + r * 0.24, cy + r * 0.28),
                QPointF(cx + r * 0.52, cy + r * 0.02),
                QPointF(cx + r * 0.78, cy + r * 0.52)]))


class PortraitCard(QFrame):
    """Карточка отряда: портрет сверху, растворяющийся в цвет карточки."""

    RADIUS = 12.0

    def __init__(self, palette, parent=None):
        super().__init__(parent)
        self.setProperty('role', 'card')
        self.pal = palette
        self.src = None
        self.header = None
        self._band = 150
        self._cache = None
        self._key = None

    def set_palette(self, palette):
        self.pal = palette
        self._invalidate()
        self.update()

    def set_portrait(self, pixmap):
        self.src = pixmap if (pixmap and not pixmap.isNull()) else None
        self._invalidate()
        self.update()

    def has_portrait(self):
        return self.src is not None

    def header_height(self):
        return self._band

    def band_pixmap(self):
        self._ensure()
        return self._cache

    def _invalidate(self):
        self._cache = None
        self._key = None

    def _sync_header(self):
        self._band = band_height(self.width())
        if self.header is not None:
            self.header.setFixedHeight(self._band)

    def _ensure(self):
        dpr = self.devicePixelRatioF() or 1.0
        w = max(2, self.width() - 2)
        key = (w, self._band, dpr, self.pal['bg_secondary'], self.pal['accent'], id(self.src))
        if self._cache is None or self._key != key:
            self._cache = render_band(self.src, w, self._band, self.pal, dpr)
            self._key = key

    def resizeEvent(self, e):
        super().resizeEvent(e)
        h = band_height(self.width())
        if h != self._band:
            self._band = h
            self._sync_header()
        self._invalidate()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        self._ensure()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.drawPixmap(QPointF(1, 1), self._cache)
        p.end()