"""Монохромные иконки тулбара и вкладок боковой панели.

Рисуются кодом, без сторонних SVG и шрифтов. Отдельной лицензии нет:
рисунки — часть этого проекта. Цвет берётся из палитры темы, поэтому
одни и те же значки читаются на тёмном и светлом фоне.
"""
import math

from PyQt6.QtCore import Qt, QPointF, QRectF
from PyQt6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF


def tool_icon(kind, color, size=22):
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.8, size / 11.0))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    _draw(painter, kind, size)
    painter.end()
    return QIcon(pix)


def _draw(p, kind, size):
    m = size * 0.16
    x0, y0 = m, m
    w = size - 2 * m
    cx, cy = size / 2.0, size / 2.0

    if kind == 'play':
        p.setBrush(QColor(p.pen().color()))
        p.drawPolygon(QPolygonF([
            QPointF(x0 + w * 0.15, y0),
            QPointF(x0 + w * 0.15, y0 + w),
            QPointF(x0 + w * 0.95, cy),
        ]))
    elif kind == 'pause':
        p.setBrush(QColor(p.pen().color()))
        gap = w * 0.22
        bar = (w - gap) / 2
        p.drawRoundedRect(QRectF(x0, y0, bar, w), 1.5, 1.5)
        p.drawRoundedRect(QRectF(x0 + bar + gap, y0, bar, w), 1.5, 1.5)
    elif kind == 'next':
        p.setBrush(QColor(p.pen().color()))
        p.drawPolygon(QPolygonF([
            QPointF(x0, y0),
            QPointF(x0, y0 + w),
            QPointF(x0 + w * 0.68, cy),
        ]))
        p.drawRoundedRect(QRectF(x0 + w * 0.78, y0, w * 0.18, w), 1.2, 1.2)
    elif kind == 'undo':
        _arc_arrow(p, cx, cy, w * 0.48, left=True)
    elif kind == 'redo':
        _arc_arrow(p, cx, cy, w * 0.48, left=False)
    elif kind == 'armies':
        p.drawEllipse(QPointF(cx - w * 0.22, cy), w * 0.28, w * 0.28)
        p.drawEllipse(QPointF(cx + w * 0.22, cy), w * 0.28, w * 0.28)
    elif kind == 'create':
        p.drawEllipse(QPointF(cx, cy), w * 0.48, w * 0.48)
        p.drawLine(QPointF(cx, cy - w * 0.24), QPointF(cx, cy + w * 0.24))
        p.drawLine(QPointF(cx - w * 0.24, cy), QPointF(cx + w * 0.24, cy))
    elif kind == 'settings':
        _gear(p, cx, cy, w * 0.46)
    elif kind == 'roster':
        for i, yy in enumerate((0.12, 0.42, 0.72)):
            p.drawEllipse(QPointF(x0 + w * 0.12, y0 + w * yy + w * 0.08), w * 0.08, w * 0.08)
            p.drawLine(QPointF(x0 + w * 0.32, y0 + w * yy + w * 0.08),
                       QPointF(x0 + w, y0 + w * yy + w * 0.08))
    elif kind == 'log':
        p.drawRoundedRect(QRectF(x0, y0, w, w), 2, 2)
        for frac in (0.28, 0.48, 0.68):
            p.drawLine(QPointF(x0 + w * 0.18, y0 + w * frac),
                       QPointF(x0 + w * 0.82, y0 + w * frac))
    elif kind == 'book':
        p.drawLine(QPointF(cx, y0 + w * 0.08), QPointF(cx, y0 + w * 0.92))
        p.drawArc(QRectF(x0 - w * 0.05, y0, w * 0.62, w * 0.92), 0, 180 * 16)
        p.drawArc(QRectF(cx - w * 0.05, y0, w * 0.62, w * 0.92), 0, -180 * 16)
    else:
        p.drawEllipse(QPointF(cx, cy), w * 0.2, w * 0.2)


def _arc_arrow(p, cx, cy, radius, left):
    rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
    if left:
        p.drawArc(rect, 40 * 16, 250 * 16)
        tip = QPointF(cx + math.cos(math.radians(40)) * radius,
                      cy - math.sin(math.radians(40)) * radius)
        _head(p, tip, math.radians(40 + 100))
    else:
        p.drawArc(rect, -40 * 16, -250 * 16)
        tip = QPointF(cx + math.cos(math.radians(-40)) * radius,
                      cy - math.sin(math.radians(-40)) * radius)
        _head(p, tip, math.radians(-40 - 100))


def _head(p, tip, direction):
    wing = 5.0
    left = tip + QPointF(math.cos(direction + 0.6) * wing, -math.sin(direction + 0.6) * wing)
    right = tip + QPointF(math.cos(direction - 0.6) * wing, -math.sin(direction - 0.6) * wing)
    color = QColor(p.pen().color())
    p.setBrush(color)
    p.drawPolygon(QPolygonF([tip, left, right]))
    p.setBrush(Qt.BrushStyle.NoBrush)


def _gear(p, cx, cy, radius):
    p.drawEllipse(QPointF(cx, cy), radius * 0.42, radius * 0.42)
    inner = radius * 0.62
    outer = radius
    for i in range(8):
        ang = i * math.pi / 4.0
        p.drawLine(
            QPointF(cx + math.cos(ang) * inner, cy + math.sin(ang) * inner),
            QPointF(cx + math.cos(ang) * outer, cy + math.sin(ang) * outer),
        )
