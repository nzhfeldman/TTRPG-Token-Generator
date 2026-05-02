"""Shared utilities: image loading and reusable IconButton widget."""

import os
from PyQt6.QtWidgets import QWidget, QToolTip
from PyQt6.QtGui import QPixmap, QPainter, QPen, QBrush, QColor, QFont, QPolygonF
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer


# ---------------------------------------------------------------------------
# Image loading
# ---------------------------------------------------------------------------

def load_pixmap(path: str, max_size: int = 1024) -> QPixmap:
    """Load any supported image file and return it as a QPixmap.

    Raster files (PNG, WebP) are returned at their native pixel dimensions.
    SVG files are rasterized so their longest side is at most max_size pixels,
    with the natural aspect ratio preserved.
    """
    if path.lower().endswith(".svg"):
        return _svg_to_pixmap(path, max_size)
    return QPixmap(path)


def _svg_to_pixmap(path: str, max_size: int) -> QPixmap:
    """Rasterize an SVG file to a QPixmap using Qt's built-in SVG renderer."""
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return QPixmap()

    natural = renderer.defaultSize()
    if natural.isEmpty():
        w = h = max_size
    elif natural.width() >= natural.height():
        w = max_size
        h = max(1, round(max_size * natural.height() / natural.width()))
    else:
        h = max_size
        w = max(1, round(max_size * natural.width() / natural.height()))

    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


# ---------------------------------------------------------------------------
# IconButton
# ---------------------------------------------------------------------------

class IconButton(QWidget):
    """Circular colored button with a programmatically-drawn black icon.

    Features:
    - Pointer cursor on hover
    - Circle lightens 20 % on hover
    - 7-word tooltip appears after exactly 200 ms (not the system default)
    - Emits clicked() on left press

    Icon types: 'eraser', 'printer', 'catch', 'throw', 'sponge',
                'folder', 'pdf'
    """

    clicked = pyqtSignal()

    _DIAM = 32   # circle diameter in pixels

    def __init__(self, icon_type: str, color: QColor, tooltip: str, parent=None):
        super().__init__(parent)
        self._icon_type = icon_type
        self._color = color
        self._hovered = False

        size = self._DIAM + 6
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Disable Qt's own tooltip — we manage the 200 ms delay ourselves
        self.setToolTip("")
        self._tooltip_text = tooltip
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.setInterval(200)
        self._tooltip_timer.timeout.connect(self._show_tooltip)

    # ------------------------------------------------------------------
    # Tooltip
    # ------------------------------------------------------------------

    def _show_tooltip(self):
        if self._hovered:
            QToolTip.showText(self.mapToGlobal(self.rect().center()),
                              self._tooltip_text, self)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def enterEvent(self, event):
        self._hovered = True
        self._tooltip_timer.start()
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self._tooltip_timer.stop()
        QToolTip.hideText()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        off = 3   # offset so the circle has breathing room
        c = self._color.lighter(120) if self._hovered else self._color
        painter.setBrush(QBrush(c))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(off, off, self._DIAM, self._DIAM)

        # Icon drawn in black inside the circle
        painter.setPen(QPen(QColor(0, 0, 0), 1.8,
                            Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap,
                            Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        icon_rect = QRectF(off, off, self._DIAM, self._DIAM)
        self._draw_icon(painter, icon_rect)
        painter.end()

    # ------------------------------------------------------------------
    # Icon drawing (all in local coords of the circle rect)
    # ------------------------------------------------------------------

    def _draw_icon(self, p: QPainter, r: QRectF):
        cx, cy = r.center().x(), r.center().y()
        s = r.width() * 0.28   # half-unit for sizing sub-shapes

        if self._icon_type == 'eraser':
            self._icon_eraser(p, cx, cy, s)
        elif self._icon_type == 'printer':
            self._icon_printer(p, cx, cy, s)
        elif self._icon_type == 'catch':
            self._icon_catch(p, cx, cy, s)
        elif self._icon_type == 'throw':
            self._icon_throw(p, cx, cy, s)
        elif self._icon_type == 'sponge':
            self._icon_sponge(p, cx, cy, s)
        elif self._icon_type == 'folder':
            self._icon_folder(p, cx, cy, s)
        elif self._icon_type == 'pdf':
            self._icon_pdf(p, cx, cy, s)

    def _icon_eraser(self, p, cx, cy, s):
        # Tilted rectangle (body) + smaller rectangle (tip, right side)
        p.save()
        p.translate(cx, cy)
        p.rotate(-25)
        # Body
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawRect(QRectF(-s * 1.4, -s * 0.55, s * 1.9, s * 1.1))
        # Tip (lighter, right end) — erase with white then re-outline
        p.setBrush(QBrush(QColor(80, 80, 80)))
        p.drawRect(QRectF(s * 0.45, -s * 0.55, s * 0.55, s * 1.1))
        # Divider line
        p.setPen(QPen(QColor(200, 200, 200), 1.5))
        p.drawLine(QPointF(s * 0.45, -s * 0.55), QPointF(s * 0.45, s * 0.55))
        p.restore()

    def _icon_printer(self, p, cx, cy, s):
        # Paper (white rect sticking up from printer body)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(QPen(QColor(0, 0, 0), 1.5))
        p.drawRect(QRectF(cx - s * 0.65, cy - s * 1.3, s * 1.3, s * 1.05))
        # Printer body (wider dark box)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawRect(QRectF(cx - s, cy - s * 0.4, s * 2.0, s * 1.1))
        # Output slot indicator (thin line at bottom of body)
        p.setPen(QPen(QColor(255, 255, 255), 1.5))
        p.drawLine(QPointF(cx - s * 0.55, cy + s * 0.5),
                   QPointF(cx + s * 0.55, cy + s * 0.5))

    def _icon_catch(self, p, cx, cy, s):
        # Open hand: palm + 4 finger bumps on top
        # Palm
        p.drawRoundedRect(QRectF(cx - s * 0.9, cy - s * 0.3, s * 1.8, s * 1.3),
                          s * 0.3, s * 0.3)
        # Fingers (4 rounded bumps)
        fw = s * 0.35
        fh = s * 0.85
        for i in range(4):
            fx = cx - s * 0.85 + i * (fw + s * 0.07)
            p.drawRoundedRect(QRectF(fx, cy - s * 1.1, fw, fh),
                              fw * 0.5, fw * 0.5)
        # Thumb (side)
        p.drawRoundedRect(QRectF(cx + s * 0.9, cy + s * 0.0, s * 0.45, s * 0.7),
                          s * 0.2, s * 0.2)

    def _icon_throw(self, p, cx, cy, s):
        # Closed fist (rounded rect) + ball (circle) upper right
        # Fist
        p.drawRoundedRect(QRectF(cx - s * 1.0, cy - s * 0.2, s * 1.5, s * 1.2),
                          s * 0.3, s * 0.3)
        # Knuckle lines
        p.setPen(QPen(QColor(255, 255, 255), 1.2))
        for i in range(3):
            bx = cx - s * 0.6 + i * s * 0.45
            p.drawLine(QPointF(bx, cy - s * 0.2),
                       QPointF(bx, cy + s * 0.3))
        p.setPen(QPen(QColor(0, 0, 0), 1.8,
                     Qt.PenStyle.SolidLine,
                     Qt.PenCapStyle.RoundCap,
                     Qt.PenJoinStyle.RoundJoin))
        # Ball (circle)
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawEllipse(QRectF(cx + s * 0.6, cy - s * 1.2, s * 0.9, s * 0.9))
        # Motion lines from ball
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0), 1.5))
        p.drawLine(QPointF(cx + s * 0.45, cy - s * 0.75),
                   QPointF(cx + s * 0.6, cy - s * 0.85))
        p.drawLine(QPointF(cx + s * 0.3, cy - s * 0.55),
                   QPointF(cx + s * 0.5, cy - s * 0.4))

    def _icon_sponge(self, p, cx, cy, s):
        # Rectangle with dot-grid texture
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawRoundedRect(QRectF(cx - s, cy - s * 0.75, s * 2.0, s * 1.5),
                          s * 0.2, s * 0.2)
        # White dot grid (porous texture)
        p.setBrush(QBrush(QColor(255, 255, 255)))
        p.setPen(Qt.PenStyle.NoPen)
        ds = s * 0.22
        for row in range(3):
            for col in range(4):
                dx = cx - s * 0.75 + col * s * 0.5
                dy = cy - s * 0.5 + row * s * 0.5
                p.drawEllipse(QRectF(dx, dy, ds, ds))

    def _icon_folder(self, p, cx, cy, s):
        # Classic folder: base rectangle + tab on top-left
        # Tab
        tab = QPolygonF([
            QPointF(cx - s, cy - s * 0.3),
            QPointF(cx - s, cy - s * 0.85),
            QPointF(cx - s * 0.1, cy - s * 0.85),
            QPointF(cx + s * 0.2, cy - s * 0.3),
        ])
        p.setBrush(QBrush(QColor(0, 0, 0)))
        p.drawPolygon(tab)
        # Body
        p.drawRoundedRect(QRectF(cx - s, cy - s * 0.4, s * 2.0, s * 1.35),
                          s * 0.15, s * 0.15)

    def _icon_pdf(self, p, cx, cy, s):
        # "PDF" text centered
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0)))
        font = QFont("Arial", max(7, int(s * 1.1)), QFont.Weight.Bold)
        p.setFont(font)
        p.drawText(QRectF(cx - s * 1.4, cy - s * 0.75, s * 2.8, s * 1.5),
                   Qt.AlignmentFlag.AlignCenter, "PDF")
