"""Автоматический кадр портрета: анализ арта -> композиция -> рендер полосы.

Никаких ручек: пользователь не должен кадрировать. Алгоритм сам
  1) оценивает цвет фона по углам и срезает пустые поля (bbox контента);
  2) считает карту резкости и находит якорь на детальном участке (морда/голова);
  3) вырезает светлый фон заливкой от границ с растушёвкой;
  4) выбирает композицию: широкий арт заполняет полосу, высокий/мелкий —
     целиком по нижнему краю на размытой подложке (без мыльного апскейла);
  5) рендерит в devicePixelRatio и растворяет низ в цвет карточки.
Анализ и вырезка кэшируются по id QPixmap — считаются один раз на картинку.
"""
from collections import deque

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import (QPixmap, QPainter, QPainterPath, QColor, QLinearGradient,
                         QRadialGradient, QBrush, QImage, qRed, qGreen, qBlue)

_ANALYSIS = {}
_CUTOUT = {}
KEEP = 24          # сколько записей держим в кэше анализа


def _rgb(im, x, y):
    v = im.pixel(x, y)
    return qRed(v), qGreen(v), qBlue(v)


def _dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _small(pix, side):
    im = pix.toImage()
    if max(im.width(), im.height()) > side:
        im = im.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return im.convertToFormat(QImage.Format.Format_RGB32)


def analyze(src):
    """bbox контента (норм. 0..1), якорь резкости, цвет фона, светлый ли фон."""
    key = id(src)
    hit = _ANALYSIS.get(key)
    if hit is not None:
        return hit
    im = _small(src, 96)
    w, h = im.width(), im.height()
    grid = [[_rgb(im, x, y) for x in range(w)] for y in range(h)]

    corners = []
    for xs, ys in ((range(0, 3), range(0, 3)),
                   (range(w - 3, w), range(0, 3)),
                   (range(0, 3), range(h - 3, h)),
                   (range(w - 3, w), range(h - 3, h))):
        for y in ys:
            for x in xs:
                if 0 <= x < w and 0 <= y < h:
                    corners.append(grid[y][x])
    bg = tuple(sum(c[i] for c in corners) // max(1, len(corners)) for i in range(3))

    tol = 46
    x0, y0, x1, y1 = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if _dist(grid[y][x], bg) > tol:
                x0 = min(x0, x); y0 = min(y0, y)
                x1 = max(x1, x); y1 = max(y1, y)
    if x1 - x0 < w * 0.12 or y1 - y0 < h * 0.12:
        x0, y0, x1, y1 = 0, 0, w - 1, h - 1

    gray = [[(grid[y][x][0] * 299 + grid[y][x][1] * 587 + grid[y][x][2] * 114) // 1000
             for x in range(w)] for y in range(h)]
    sx = sy = sw = 0.0
    for y in range(y0, y1):
        for x in range(x0, x1):
            g = abs(gray[y][x + 1] - gray[y][x]) + abs(gray[y + 1][x] - gray[y][x])
            if g > 10:
                sx += x * g; sy += y * g; sw += g
    if sw > 0:
        fx = (sx / sw - x0) / max(1, (x1 - x0))
        fy = (sy / sw - y0) / max(1, (y1 - y0))
    else:
        fx, fy = 0.5, 0.35
    fy = max(0.0, min(1.0, fy * 0.75))          # тянем якорь выше центра: головы

    res = {'bbox': (x0 / w, y0 / h, (x1 + 1) / w, (y1 + 1) / h),
           'focus': (max(0.0, min(1.0, fx)), fy),
           'bg': bg,
           'light': (bg[0] * 299 + bg[1] * 587 + bg[2] * 114) / 1000 > 150}
    if len(_ANALYSIS) > KEEP:
        _ANALYSIS.clear()
    _ANALYSIS[key] = res
    return res


def cutout(src, bg, tol=52):
    """Убирает фон, связный с границами (заливка), растушёвывает край."""
    key = (id(src), bg, tol)
    hit = _CUTOUT.get(key)
    if hit is not None:
        return hit
    im = _small(src, 190)
    w, h = im.width(), im.height()
    grid = [[_rgb(im, x, y) for x in range(w)] for y in range(h)]
    gone = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            if _dist(grid[y][x], bg) <= tol and not gone[y * w + x]:
                gone[y * w + x] = 1
                q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if _dist(grid[y][x], bg) <= tol and not gone[y * w + x]:
                gone[y * w + x] = 1
                q.append((x, y))
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not gone[ny * w + nx] \
                    and _dist(grid[ny][nx], bg) <= tol:
                gone[ny * w + nx] = 1
                q.append((nx, ny))

    mask = QImage(w, h, QImage.Format.Format_ARGB32)
    for y in range(h):
        for x in range(w):
            mask.setPixel(x, y, QColor(0, 0, 0, 0 if gone[y * w + x] else 255).rgba())
    mask = mask.scaled(max(1, w // 2), max(1, h // 2),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    mask = mask.scaled(src.width(), src.height(),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)

    out = QPixmap(src.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.drawPixmap(0, 0, src)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    p.drawImage(0, 0, mask)
    p.end()
    if len(_CUTOUT) > KEEP:
        _CUTOUT.clear()
    _CUTOUT[key] = out
    return out


def _cover(src, w, h, zoom=1.0, focus=(0.5, 0.35)):
    big = src.scaled(max(1, int(w * zoom)), max(1, int(h * zoom)),
                     Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    sx = max(0, min(big.width() - w, (big.width() - w) * focus[0]))
    sy = max(0, min(big.height() - h, (big.height() - h) * focus[1]))
    return big.copy(int(sx), int(sy), w, h)


def _bokeh(pix):
    """Мягкое размытие: три ступени вниз + плавный подъём (не каша из 20 px)."""
    w, h = max(1, pix.width()), max(1, pix.height())
    k = max(4, min(16, min(w, h) // 16))
    small = pix.scaled(max(1, w // k), max(1, h // k),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    mid = small.scaled(max(1, w // 2), max(1, h // 2),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    return mid.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                      Qt.TransformationMode.SmoothTransformation)


def band_height(card_w):
    return int(max(104, min(228, card_w * 0.40)))


def render_band(src, w, h, pal, dpr=1.0):
    W, H = max(2, int(w * dpr)), max(2, int(h * dpr))
    out = QPixmap(W, H)
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    r = 11.0 * dpr
    path = QPainterPath()
    path.moveTo(0, H); path.lineTo(0, r); path.quadTo(0, 0, r, 0)
    path.lineTo(W - r, 0); path.quadTo(W, 0, W, r)
    path.lineTo(W, H); path.closeSubpath()
    p.setClipPath(path)
    base = QColor(pal['bg_secondary'])
    full = QRectF(0, 0, W, H)

    if src is None or src.isNull():
        g = QLinearGradient(0, 0, W, H)
        a = QColor(pal['accent']); a.setAlpha(80)
        g.setColorAt(0.0, a); g.setColorAt(1.0, QColor(base))
        p.fillRect(full, QBrush(g))
        glow = QRadialGradient(W * 0.5, H * 0.1, max(W, H) * 0.8)
        a2 = QColor(pal['accent']); a2.setAlpha(72)
        a3 = QColor(pal['accent']); a3.setAlpha(0)
        glow.setColorAt(0.0, a2); glow.setColorAt(1.0, a3)
        p.fillRect(full, QBrush(glow))
    else:
        if max(src.width(), src.height()) > 2400:
            src = src.scaled(2400, 2400, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        try:
            info = analyze(src)
        except Exception:
            info = {'bbox': (0.0, 0.0, 1.0, 1.0), 'focus': (0.5, 0.3),
                    'bg': (0, 0, 0), 'light': False}
        bx0, by0, bx1, by1 = info['bbox']
        box = (int(bx0 * src.width()), int(by0 * src.height()),
               max(1, int((bx1 - bx0) * src.width())),
               max(1, int((by1 - by0) * src.height())))
        trimmed = src.copy(*box)
        art = trimmed
        if info['light']:
            try:
                art = cutout(trimmed, info['bg'])
            except Exception:
                art = trimmed

        p.drawPixmap(0, 0, _bokeh(_cover(trimmed, W, H, 1.3, info['focus'])))
        p.fillRect(full, QColor(0, 0, 0, 120))
        vg = QRadialGradient(W * 0.5, H * 0.4, max(W, H) * 0.7)
        vg.setColorAt(0.0, QColor(0, 0, 0, 0))
        vg.setColorAt(1.0, QColor(0, 0, 0, 110))
        p.fillRect(full, QBrush(vg))

        subj_ar = art.width() / max(1, art.height())
        band_ar = W / max(1, H)
        weak = art.width() < W * 0.55
        if subj_ar >= band_ar * 0.72 and not weak:
            p.drawPixmap(0, 0, _cover(art, W, H, 1.0, info['focus']))
        else:
            limit = 1.0 if weak else 2.2
            k = min((H * 1.02) / art.height(), (W * 0.94) / art.width(), limit)
            tw, th = max(1, int(art.width() * k)), max(1, int(art.height() * k))
            fg = art.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(QPointF((W - fg.width()) / 2.0, H - fg.height()), fg)

        top = QLinearGradient(0, 0, 0, H * 0.34)
        top.setColorAt(0.0, QColor(0, 0, 0, 105))
        top.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, W, H * 0.34), QBrush(top))

    fstart = H * 0.30
    fade = QLinearGradient(0, fstart, 0, H)
    c0 = QColor(base); c0.setAlpha(0)
    cm = QColor(base); cm.setAlpha(190)
    c1 = QColor(base); c1.setAlpha(255)
    fade.setColorAt(0.0, c0); fade.setColorAt(0.62, cm); fade.setColorAt(1.0, c1)
    p.fillRect(QRectF(0, fstart, W, H - fstart + 1), QBrush(fade))
    p.end()
    return out