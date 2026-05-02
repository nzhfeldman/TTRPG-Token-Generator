import math
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageDraw
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu,
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QDialogButtonBox,
    QGraphicsItem, QWidget, QHBoxLayout, QVBoxLayout, QLabel, QGroupBox,
    QPushButton, QAbstractSpinBox, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSizeF, QTimer
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPixmap, QTransform, QPainterPath, QImage,
    QFont, QFontMetrics,
)
from panels.utils import load_pixmap, IconButton

GRID_SIZE = 40
HANDLE_SIZE = 9
ROTATE_OFFSET = 28
LAYER_BG = -5
LAYER_FIG = 0
LAYER_FRAME = 5

_SCALE_HANDLES = {
    'tl': (0, 0), 't': (0.5, 0), 'tr': (1, 0),
    'l':  (0, 0.5),              'r':  (1, 0.5),
    'bl': (0, 1), 'b': (0.5, 1), 'br': (1, 1),
}
_ALL_HANDLES = list(_SCALE_HANDLES.keys()) + ['rot']


def _dot(a: QPointF, b: QPointF) -> float:
    return a.x() * b.x() + a.y() * b.y()

def _norm(v: QPointF) -> QPointF:
    mag = math.sqrt(v.x() ** 2 + v.y() ** 2)
    return QPointF(v.x() / mag, v.y() / mag) if mag > 1e-9 else QPointF(1.0, 0.0)


# ------------------------------------------------------------------
# PIL / QPixmap helpers
# ------------------------------------------------------------------

def _qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    qimage = pixmap.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimage.width(), qimage.height()
    ptr = qimage.bits()
    ptr.setsize(h * w * 4)
    return Image.fromarray(
        np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy(), 'RGBA'
    )


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    qimage = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def _load_frame_pil(path: str, max_size: int = 1024) -> 'Image.Image | None':
    try:
        if path.lower().endswith('.svg'):
            pixmap = load_pixmap(path, max_size=max_size)
            if pixmap.isNull():
                return None
            return _qpixmap_to_pil(pixmap)
        img = Image.open(path).convert('RGBA')
        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        return img
    except Exception:
        return None


def _apply_thinning(pil_img: Image.Image, pixels: int) -> Image.Image:
    """Erode the frame from its inner boundary by `pixels` pixels.

    Dilates the inner transparent hole outward, eating into the frame ring
    from the inside only. The outer edge is unchanged.
    """
    if pixels <= 0:
        return pil_img

    arr   = np.array(pil_img)
    alpha = arr[:, :, 3]
    w, h  = pil_img.size

    # Build binary: opaque pixels = 255
    binary = np.where(alpha > 5, 255, 0).astype(np.uint8)
    bin_img = Image.fromarray(binary, 'L')

    # Flood-fill from corner to mark the exterior (pixels outside the frame ring)
    bordered = Image.new('L', (w + 2, h + 2), 0)
    bordered.paste(bin_img, (1, 1))
    ImageDraw.floodfill(bordered, (0, 0), 128)
    bordered = bordered.crop((1, 1, w + 1, h + 1))
    b_arr = np.array(bordered)

    exterior         = b_arr == 128          # outside the frame's outer edge
    interior_transp  = (alpha <= 5) & ~exterior   # inner hole

    # Dilate the inner hole by `pixels` pixels
    hole_img = Image.fromarray((interior_transp.astype(np.uint8) * 255), 'L')
    for _ in range(pixels):
        hole_img = hole_img.filter(ImageFilter.MaxFilter(3))

    dilated = np.array(hole_img) > 0
    result  = arr.copy()
    result[dilated, 3] = 0
    return Image.fromarray(result, 'RGBA')


def _shift_hue(img_rgb: Image.Image, shift_deg: float) -> Image.Image:
    arr = np.array(img_rgb, dtype=np.float32) / 255.0
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

    maxc  = np.maximum(np.maximum(r, g), b)
    minc  = np.minimum(np.minimum(r, g), b)
    v     = maxc
    delta = maxc - minc
    s = np.zeros_like(maxc)
    np.divide(delta, maxc, out=s, where=maxc > 0)

    h  = np.zeros_like(maxc)
    nz = delta > 0
    rm = nz & (maxc == r)
    gm = nz & (maxc == g)
    bm = nz & (maxc == b)
    h[rm] = ((g[rm] - b[rm]) / delta[rm]) % 6.0
    h[gm] = (b[gm] - r[gm]) / delta[gm] + 2.0
    h[bm] = (r[bm] - g[bm]) / delta[bm] + 4.0
    h = (h / 6.0 + shift_deg / 360.0) % 1.0

    h6 = h * 6.0
    i  = np.floor(h6).astype(np.int32) % 6
    f  = h6 - np.floor(h6)
    p  = v * (1.0 - s)
    q  = v * (1.0 - f * s)
    t2 = v * (1.0 - (1.0 - f) * s)

    out_r = np.choose(i, [v,  q,  p,  p, t2,  v])
    out_g = np.choose(i, [t2, v,  v,  q,  p,  p])
    out_b = np.choose(i, [p,  p, t2,  v,  v,  q])

    ach = s == 0
    out_r[ach] = v[ach]; out_g[ach] = v[ach]; out_b[ach] = v[ach]

    return Image.fromarray(
        np.clip(np.stack([out_r, out_g, out_b], axis=2) * 255.0, 0, 255
                ).astype(np.uint8), 'RGB'
    )


def _apply_alpha(img: Image.Image, alpha_pct: int) -> Image.Image:
    """Scale the alpha channel of an RGBA image by alpha_pct/100."""
    if alpha_pct >= 100:
        return img
    factor = max(0.0, alpha_pct / 100.0)
    r, g, b, a = img.split()
    a = a.point(lambda x: round(x * factor))
    return Image.merge('RGBA', (r, g, b, a))


def _apply_color_adjustments(
    img: Image.Image, hue_shift: int, value_adj: int, intensity_adj: int
) -> Image.Image:
    if hue_shift == 0 and value_adj == 0 and intensity_adj == 0:
        return img
    r, g, b, a = img.split()
    rgb = Image.merge('RGB', (r, g, b))
    if intensity_adj != 0:
        rgb = ImageEnhance.Color(rgb).enhance(max(0.0, 1.0 + intensity_adj / 100.0))
    if value_adj != 0:
        rgb = ImageEnhance.Brightness(rgb).enhance(max(0.0, 1.0 + value_adj / 100.0))
    if hue_shift != 0:
        rgb = _shift_hue(rgb, float(hue_shift))
    r2, g2, b2 = rgb.split()
    return Image.merge('RGBA', (r2, g2, b2, a))


# ------------------------------------------------------------------
# TokenItem
# ------------------------------------------------------------------

class TokenItem(QGraphicsObject):
    removal_requested = pyqtSignal(object)

    def __init__(self, pixmap: QPixmap, path: str, category: str, layer: int):
        super().__init__()
        self._pixmap = pixmap
        self.path = path
        self.category = category
        self._layer = layer
        self._sx = 1.0
        self._sy = 1.0
        self._rotation_deg = 0.0

        w, h = pixmap.width(), pixmap.height()
        self._pw = w
        self._ph = h

        self._drag_pixmap   = self._make_drag_pixmap(pixmap)
        self._active_pixmap = pixmap

        self.setZValue(layer)
        self.setTransformOriginPoint(w / 2, h / 2)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self._apply_transform()

        self._active_handle: str | None = None
        self._drag_start_sx = 1.0
        self._drag_start_sy = 1.0
        self._drag_start_rot = 0.0
        self._drag_center_scene = QPointF()
        self._drag_x_axis = QPointF(1.0, 0.0)
        self._drag_y_axis = QPointF(0.0, 1.0)
        self._drag_start_dist_x = 1.0
        self._drag_start_dist_y = 1.0

    def _set_smooth_rendering(self, smooth: bool) -> None:
        if self.scene():
            hint = QPainter.RenderHint.SmoothPixmapTransform
            for view in self.scene().views():
                view.setRenderHint(hint, smooth)

    def _make_drag_pixmap(self, pixmap: QPixmap, max_size: int = 512) -> QPixmap:
        if pixmap.width() <= max_size and pixmap.height() <= max_size:
            return pixmap
        return pixmap.scaled(max_size, max_size,
                             Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.FastTransformation)

    def _apply_transform(self):
        w, h = self._pw, self._ph
        t = QTransform()
        t.translate(w / 2, h / 2)
        t.scale(self._sx, self._sy)
        t.translate(-w / 2, -h / 2)
        self.setTransform(t)
        self.setRotation(self._rotation_deg)

    @property
    def layer(self) -> int:
        return self._layer

    @layer.setter
    def layer(self, value: int):
        self._layer = value
        self.setZValue(value)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._pw, self._ph).adjusted(
            -HANDLE_SIZE, -HANDLE_SIZE - ROTATE_OFFSET, HANDLE_SIZE, HANDLE_SIZE
        )

    def _item_rect(self) -> QRectF:
        return QRectF(0, 0, self._pw, self._ph)

    def _handle_center(self, name: str) -> QPointF:
        r = self._item_rect()
        if name == 'rot':
            return QPointF(r.width() / 2, -ROTATE_OFFSET)
        ax, ay = _SCALE_HANDLES[name]
        return QPointF(r.x() + r.width() * ax, r.y() + r.height() * ay)

    def _handle_rect(self, name: str) -> QRectF:
        c = self._handle_center(name)
        s = HANDLE_SIZE
        return QRectF(c.x() - s / 2, c.y() - s / 2, s, s)

    def _hit_handle(self, local_pos: QPointF) -> str | None:
        if not self.isSelected():
            return None
        for name in _ALL_HANDLES:
            if self._handle_rect(name).adjusted(-14, -14, 14, 14).contains(local_pos):
                return name
        return None

    def paint(self, painter: QPainter, option, widget=None):
        r = self._item_rect()
        painter.drawPixmap(0, 0, self._pw, self._ph, self._active_pixmap)
        rendering = self.scene() and getattr(self.scene(), '_is_rendering', False)
        if self.isSelected() and not rendering:
            painter.save()
            painter.setPen(QPen(QColor(0, 140, 255), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)
            cx = r.width() / 2
            painter.setPen(QPen(QColor(0, 200, 100), 1))
            painter.drawLine(QPointF(cx, 0), QPointF(cx, -ROTATE_OFFSET))
            painter.setPen(QPen(QColor(0, 100, 200), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
            for name in _SCALE_HANDLES:
                painter.drawRect(self._handle_rect(name))
            painter.setPen(QPen(QColor(0, 160, 80), 1))
            painter.setBrush(QBrush(QColor(0, 220, 100, 200)))
            painter.drawEllipse(self._handle_rect('rot'))
            painter.restore()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._active_pixmap = self._drag_pixmap
            self._set_smooth_rendering(False)
            handle = self._hit_handle(event.pos())
            if handle:
                self._active_handle = handle
                self._drag_start_sx  = self._sx
                self._drag_start_sy  = self._sy
                self._drag_start_rot = self._rotation_deg
                cx = self._pw / 2; cy = self._ph / 2
                self._drag_center_scene = self.mapToScene(QPointF(cx, cy))
                origin = self.mapToScene(QPointF(0.0, 0.0))
                self._drag_x_axis = _norm(self.mapToScene(QPointF(1.0, 0.0)) - origin)
                self._drag_y_axis = _norm(self.mapToScene(QPointF(0.0, 1.0)) - origin)
                start_offset = event.scenePos() - self._drag_center_scene
                self._drag_start_dist_x = _dot(start_offset, self._drag_x_axis)
                self._drag_start_dist_y = _dot(start_offset, self._drag_y_axis)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._active_handle:
            handle = self._active_handle
            if handle == 'rot':
                center = self._drag_center_scene
                sv = event.scenePos() - center
                pv = self.mapToScene(QPointF(self._pw / 2, 0)) - center
                base_a = math.atan2(-pv.y(), pv.x())
                curr_a = math.atan2(-sv.y(), sv.x())
                self._rotation_deg = self._drag_start_rot + math.degrees(curr_a - base_a)
                self._apply_transform()
            else:
                curr_offset = event.scenePos() - self._drag_center_scene
                curr_dx = _dot(curr_offset, self._drag_x_axis)
                curr_dy = _dot(curr_offset, self._drag_y_axis)
                sx, sy  = self._drag_start_sx, self._drag_start_sy
                ax, ay  = _SCALE_HANDLES[handle]
                is_corner = (ax != 0.5) and (ay != 0.5)
                if is_corner:
                    sign_x = 1.0 if ax > 0.5 else -1.0
                    sign_y = 1.0 if ay > 0.5 else -1.0
                    start_diag = sign_x * self._drag_start_dist_x + sign_y * self._drag_start_dist_y
                    curr_diag  = sign_x * curr_dx + sign_y * curr_dy
                    if abs(start_diag) > 0.5:
                        k  = curr_diag / start_diag
                        sx = max(0.05, self._drag_start_sx * k)
                        sy = max(0.05, self._drag_start_sy * k)
                else:
                    if ('r' in handle or 'l' in handle) and abs(self._drag_start_dist_x) > 0.5:
                        sx = max(0.05, self._drag_start_sx * curr_dx / self._drag_start_dist_x)
                    if ('b' in handle or 't' in handle) and abs(self._drag_start_dist_y) > 0.5:
                        sy = max(0.05, self._drag_start_sy * curr_dy / self._drag_start_dist_y)
                self._sx, self._sy = sx, sy
                self._apply_transform()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._active_handle = None
        self._active_pixmap = self._pixmap
        self._set_smooth_rendering(True)
        self.update()
        if self.scene():
            self.scene().interaction_ended.emit()
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        handle = self._hit_handle(event.pos())
        cursors = {
            'tl': Qt.CursorShape.SizeFDiagCursor, 'tr': Qt.CursorShape.SizeBDiagCursor,
            'bl': Qt.CursorShape.SizeBDiagCursor, 'br': Qt.CursorShape.SizeFDiagCursor,
            't':  Qt.CursorShape.SizeVerCursor,   'b':  Qt.CursorShape.SizeVerCursor,
            'l':  Qt.CursorShape.SizeHorCursor,   'r':  Qt.CursorShape.SizeHorCursor,
            'rot': Qt.CursorShape.CrossCursor,
        }
        self.setCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor))

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def contextMenuEvent(self, event):
        menu = QMenu()
        layer_act  = menu.addAction(f"Set Layer…  (current: {self._layer})")
        pos_act    = menu.addAction("Set Position…")
        scale_act  = menu.addAction("Set Scale…")
        rot_act    = menu.addAction("Set Rotation…")
        menu.addSeparator()
        remove_act = menu.addAction("Remove from Workspace")
        action = menu.exec(event.screenPos())
        if action == layer_act:
            val, ok = _int_dialog("Set Layer", "Layer:", self._layer, -999, 999)
            if ok: self.layer = val
        elif action == pos_act:
            self._show_pos_dialog()
        elif action == scale_act:
            self._show_scale_dialog()
        elif action == rot_act:
            val, ok = _float_dialog("Set Rotation", "Degrees:", self._rotation_deg, -360, 360)
            if ok:
                self._rotation_deg = val; self._apply_transform()
        elif action == remove_act:
            self.removal_requested.emit(self)

    def _show_pos_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Set Position")
        form = QFormLayout(dlg)
        xs = _make_dspin(-100000, 100000, self.x())
        ys = _make_dspin(-100000, 100000, self.y())
        form.addRow("X:", xs); form.addRow("Y:", ys)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec(): self.setPos(xs.value(), ys.value())

    def _show_scale_dialog(self):
        dlg = QDialog()
        dlg.setWindowTitle("Set Scale")
        form = QFormLayout(dlg)
        sxs = _make_dspin(0.01, 50, self._sx, step=0.1)
        sys_ = _make_dspin(0.01, 50, self._sy, step=0.1)
        form.addRow("Scale X:", sxs); form.addRow("Scale Y:", sys_)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec():
            self._sx, self._sy = sxs.value(), sys_.value(); self._apply_transform()

    def get_state(self) -> dict:
        return {
            'path': self.path, 'category': self.category, 'layer': self._layer,
            'x': self.x(), 'y': self.y(),
            'rotation': self._rotation_deg, 'sx': self._sx, 'sy': self._sy,
        }

    @staticmethod
    def from_state(state: dict) -> 'TokenItem | None':
        pixmap = load_pixmap(state['path'], max_size=1024)
        if pixmap.isNull():
            return None
        item = TokenItem(pixmap, state['path'], state['category'], state['layer'])
        item.setPos(state['x'], state['y'])
        item._sx = state['sx']; item._sy = state['sy']
        item._rotation_deg = state['rotation']
        item._apply_transform()
        return item


# ------------------------------------------------------------------
# FrameOverlayItem
# ------------------------------------------------------------------

class FrameOverlayItem(QGraphicsObject):
    """Fixed, centred frame auto-scaled to fill a 400×400 canvas region.

    _out_width / _out_height store the export pixel dimensions; they do not
    affect the visual display (which is always auto-fit to 400×400).
    """

    def __init__(self, pixmap: QPixmap, pil_image: Image.Image, path: str):
        super().__init__()
        self.path = path
        self.category = 'Frames'

        self._pw = pixmap.width()
        self._ph = pixmap.height()
        self._pixmap = pixmap

        _THUMB = 512
        if max(pil_image.width, pil_image.height) > _THUMB:
            scale = _THUMB / max(pil_image.width, pil_image.height)
            self._pil_base = pil_image.resize(
                (int(pil_image.width * scale), int(pil_image.height * scale)),
                Image.Resampling.LANCZOS,
            )
        else:
            self._pil_base = pil_image

        self._pil_thinned: Image.Image = self._pil_base
        self._cached_thinning: int = 0

        # Export pixel dimensions — default 400 wide, height proportional
        self._out_width  = 400
        self._out_height = max(1, round(400.0 * self._ph / self._pw))

        self._rotation_deg  = 0.0
        self._thinning_px   = 0
        self._hue_shift     = 0
        self._value_adj     = 0
        self._intensity_adj = 0
        self._alpha_pct     = 100

        self.setZValue(LAYER_FRAME)
        self.setPos(-self._pw / 2, -self._ph / 2)
        self.setTransformOriginPoint(self._pw / 2, self._ph / 2)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self._apply_visual_transform()

    def _apply_visual_transform(self):
        sx = self._out_width  / self._pw
        sy = self._out_height / self._ph
        t = QTransform()
        t.translate(self._pw / 2, self._ph / 2)
        t.scale(sx, sy)
        t.translate(-self._pw / 2, -self._ph / 2)
        self.setTransform(t)
        self.setRotation(self._rotation_deg)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._pw, self._ph)

    def paint(self, painter: QPainter, option, widget=None):
        painter.drawPixmap(0, 0, self._pw, self._ph, self._pixmap)

    def update_params(
        self,
        out_width: int,
        out_height: int,
        rotation_deg: float,
        thinning_px: int,
        hue_shift: int,
        value_adj: int,
        intensity_adj: int,
        alpha_pct: int,
    ):
        thinning_changed = thinning_px != self._thinning_px
        color_changed    = (hue_shift        != self._hue_shift
                            or value_adj     != self._value_adj
                            or intensity_adj != self._intensity_adj
                            or alpha_pct     != self._alpha_pct)

        self._out_width     = out_width
        self._out_height    = out_height
        self._rotation_deg  = rotation_deg
        self._thinning_px   = thinning_px
        self._hue_shift     = hue_shift
        self._value_adj     = value_adj
        self._intensity_adj = intensity_adj
        self._alpha_pct     = alpha_pct

        if thinning_changed:
            self._pil_thinned = _apply_thinning(self._pil_base, thinning_px)
            self._cached_thinning = thinning_px
            color_changed = True

        if color_changed or thinning_changed:
            adjusted = _apply_color_adjustments(
                self._pil_thinned, hue_shift, value_adj, intensity_adj
            )
            adjusted = _apply_alpha(adjusted, alpha_pct)
            self._pixmap = _pil_to_qpixmap(adjusted)

        self._apply_visual_transform()
        self.update()

        if self.scene():
            self.scene().interaction_ended.emit()

    def get_params(self) -> tuple:
        """Return (out_width, out_height, rotation_deg, thinning_px,
                   hue_shift, value_adj, intensity_adj, alpha_pct)."""
        return (
            self._out_width, self._out_height,
            self._rotation_deg, self._thinning_px,
            self._hue_shift, self._value_adj, self._intensity_adj, self._alpha_pct,
        )

    def get_state(self) -> dict:
        return {
            'path':          self.path,
            'category':      'Frames',
            'layer':         LAYER_FRAME,
            'out_width':     self._out_width,
            'out_height':    self._out_height,
            'rotation':      self._rotation_deg,
            'thinning_px':   self._thinning_px,
            'hue_shift':     self._hue_shift,
            'value_adj':     self._value_adj,
            'intensity_adj': self._intensity_adj,
            'alpha_pct':     self._alpha_pct,
        }


# ------------------------------------------------------------------
# Scene
# ------------------------------------------------------------------

class WorkspaceScene(QGraphicsScene):
    frame_changed     = pyqtSignal(object)
    item_removed      = pyqtSignal(str, str)
    interaction_ended = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self._items: dict[str, TokenItem] = {}
        self._frame: FrameOverlayItem | None = None
        self._reference_frame_size: tuple[float, float] | None = None
        self._is_rendering: bool = False

    @property
    def frame_item(self) -> 'FrameOverlayItem | None':
        return self._frame

    def set_reference_frame_size(self, w: float, h: float):
        self._reference_frame_size = (w, h)

    def _get_effective_frame_size(self) -> 'tuple[float, float] | None':
        if self._frame is not None:
            return (float(self._frame._out_width), float(self._frame._out_height))
        return self._reference_frame_size

    def get_output_size(self) -> 'tuple[int, int]':
        """Return the current export pixel dimensions from the active frame."""
        if self._frame is not None:
            return (self._frame._out_width, self._frame._out_height)
        return (400, 400)

    def add_image(self, path: str, category: str) -> bool:
        if path in self._items:
            return True
        figs = sum(1 for i in self._items.values() if i.category == 'Figures')
        bgs  = sum(1 for i in self._items.values() if i.category == 'Backgrounds')
        if category == 'Figures'     and figs >= 8: return False
        if category == 'Backgrounds' and bgs  >= 8: return False

        if category == 'Frames' and self._frame is not None:
            self._remove_item(self._frame)

        if category == 'Frames':
            pil_img = _load_frame_pil(path)
            if pil_img is None: return False
            pixmap = _pil_to_qpixmap(pil_img)
            item = FrameOverlayItem(pixmap, pil_img, path)
            self.addItem(item)
            self._items[path] = item
            self._frame = item
            self._reference_frame_size = (float(pixmap.width()), float(pixmap.height()))
            self.frame_changed.emit(item)
        else:
            pixmap = load_pixmap(path, max_size=1024)
            if pixmap.isNull(): return False
            layer = {'Backgrounds': LAYER_BG, 'Figures': LAYER_FIG}[category]
            item = TokenItem(pixmap, path, category, layer)
            item.setPos(-pixmap.width() / 2, -pixmap.height() / 2)
            frame_size = self._get_effective_frame_size()
            if frame_size is not None:
                fw, fh = frame_size
                if category == 'Figures':
                    # Largest power-of-2 scale that keeps figure within 75% of frame
                    n = math.floor(math.log2(0.75 * fw / pixmap.width()))
                else:
                    # Smallest power-of-2 scale that covers the full frame width
                    n = math.ceil(math.log2(fw / pixmap.width()))
                item._sx = item._sy = 2.0 ** n
            else:
                item._sx = item._sy = 0.25
            item._apply_transform()
            item.removal_requested.connect(self._remove_item)
            self.addItem(item)
            self._items[path] = item

        self.interaction_ended.emit()
        return True

    def remove_image(self, path: str, _category: str):
        item = self._items.get(path)
        if item: self._remove_item(item)

    def clear_all(self):
        for item in list(self._items.values()):
            self.removeItem(item)
        self._items.clear()
        if self._frame is not None:
            self._frame = None
            self.frame_changed.emit(None)
        self.interaction_ended.emit()

    def update_frame_params(
        self, out_width: int, out_height: int, rotation_deg: float,
        thinning_px: int, hue_shift: int, value_adj: int,
        intensity_adj: int, alpha_pct: int,
    ):
        if self._frame is not None:
            self._frame.update_params(
                out_width, out_height, rotation_deg, thinning_px,
                hue_shift, value_adj, intensity_adj, alpha_pct,
            )

    def get_active_paths(self) -> set[str]:
        return set(self._items.keys())

    def get_workspace_state(self) -> list[dict]:
        return [item.get_state() for item in self._items.values()]

    def restore_workspace_state(self, states: list[dict]):
        self.clear_all()
        for state in sorted(states, key=lambda s: s.get('layer', LAYER_FRAME)):
            if state['category'] == 'Frames':
                pil_img = _load_frame_pil(state['path'])
                if pil_img is None: continue
                pixmap = _pil_to_qpixmap(pil_img)
                item = FrameOverlayItem(pixmap, pil_img, state['path'])
                item.update_params(
                    state.get('out_width', 400),
                    state.get('out_height', 400),
                    state.get('rotation', 0.0),
                    state.get('thinning_px', 0),
                    state.get('hue_shift', 0),
                    state.get('value_adj', 0),
                    state.get('intensity_adj', 0),
                    state.get('alpha_pct', 100),
                )
                self.addItem(item)
                self._items[state['path']] = item
                self._frame = item
                self.frame_changed.emit(item)
            else:
                item = TokenItem.from_state(state)
                if item is None: continue
                item.removal_requested.connect(self._remove_item)
                self.addItem(item)
                self._items[state['path']] = item

    def _remove_item(self, item):
        self._items.pop(item.path, None)
        self.removeItem(item)
        if item is self._frame:
            self._frame = None
            self.frame_changed.emit(None)
        self.item_removed.emit(item.path, item.category)
        self.interaction_ended.emit()


# ------------------------------------------------------------------
# View
# ------------------------------------------------------------------

class WorkspaceView(QGraphicsView):
    def __init__(self, scene: WorkspaceScene):
        super().__init__(scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(70, 70, 70)))
        self._pan_start = None
        self._pan_sb_x = 0
        self._pan_sb_y = 0

    def drawBackground(self, painter: QPainter, rect):
        super().drawBackground(painter, rect)
        painter.setPen(QPen(QColor(90, 90, 90), 0.5))
        left = int(rect.left()) - int(rect.left()) % GRID_SIZE
        top  = int(rect.top())  - int(rect.top())  % GRID_SIZE
        x = left
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += GRID_SIZE
        y = top
        while y <= rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += GRID_SIZE

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.pos()
            self._pan_sb_x  = self.horizontalScrollBar().value()
            self._pan_sb_y  = self.verticalScrollBar().value()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self.horizontalScrollBar().setValue(self._pan_sb_x - delta.x())
            self.verticalScrollBar().setValue(self._pan_sb_y - delta.y())
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept(); return
        super().mouseReleaseEvent(event)


# ------------------------------------------------------------------
# WorkspaceTopBar  (Files + PDF buttons)
# ------------------------------------------------------------------

class WorkspaceTopBar(QWidget):
    """Thin bar above the canvas: PDF | Files | Clear."""

    pdf_requested   = pyqtSignal()
    files_requested = pyqtSignal()
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setStyleSheet(
            "WorkspaceTopBar { background: #252525; border-bottom: 1px solid #3a3a3a; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(8)

        self._pdf_btn = IconButton(
            'pdf', QColor(32, 119, 67),
            "Extract images from a PDF file"
        )
        self._files_btn = IconButton(
            'folder', QColor(42, 84, 147),
            "Open and edit asset folder paths"
        )
        self._clear_btn = IconButton(
            'eraser', QColor(130, 35, 35),
            "Deselect all items from the workspace"
        )

        self._pdf_btn.clicked.connect(self.pdf_requested)
        self._files_btn.clicked.connect(self.files_requested)
        self._clear_btn.clicked.connect(self.clear_requested)

        layout.addStretch()
        layout.addWidget(self._pdf_btn)
        layout.addWidget(self._files_btn)
        layout.addWidget(self._clear_btn)
        layout.addStretch()


# ------------------------------------------------------------------
# FrameToolbar helpers
# ------------------------------------------------------------------

class _VerticalLabel(QWidget):
    """Draws text rotated 90° counter-clockwise (reads bottom to top)."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        fm = QFontMetrics(font)
        # Swap width/height: displayed width = text height, height = text width
        self.setFixedWidth(fm.height() + 6)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont()
        font.setPointSize(9)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(170, 170, 170))
        painter.translate(self.width() / 2, self.height() / 2)
        painter.rotate(-90)
        painter.drawText(
            QRectF(-self.height() / 2, -self.width() / 2,
                   self.height(), self.width()),
            Qt.AlignmentFlag.AlignCenter,
            self._text,
        )
        painter.end()


_STEP_BTN_STYLE = (
    "QPushButton { background: #3c3c3c; color: #ddd; border: 1px solid #5a5a5a;"
    " font-size: 12px; font-weight: bold; padding: 0px; border-radius: 2px; }"
    "QPushButton:hover { background: #525252; }"
    "QPushButton:pressed { background: #222; color: #fff; }"
)


class FrameToolbar(QWidget):
    """Two-section toolbar for frame controls, each laid out in a 2×2 grid.

    Transform — Height + Angle  (row 1)  /  Width + Thinning  (row 2)
    Colour    — Hue   + Value   (row 1)  /  Intensity + Alpha  (row 2)

    Width changes rescale Height proportionally; Height can be overridden
    independently.
    """

    # (out_width, out_height, rotation_deg, thinning_px, hue, value, intensity, alpha)
    frame_params_changed = pyqtSignal(int, int, float, int, int, int, int, int)

    _DEFAULTS = dict(width=400, height=400, angle=0, thinning=0,
                     hue=0, value=0, intensity=0, alpha=100)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEnabled(False)
        self.setStyleSheet(
            "FrameToolbar { background: #252525; border-top: 1px solid #3a3a3a; }"
        )
        _GROUP_STYLE = (
            "QGroupBox { color: #888; font-size: 9px; border: 1px solid #3a3a3a;"
            " border-radius: 4px; margin-top: 10px; padding-top: 2px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 6px; }"
        )

        outer = QHBoxLayout(self)
        outer.setContentsMargins(6, 4, 10, 4)
        outer.setSpacing(8)

        outer.addWidget(_VerticalLabel("Frame:"))

        groups_col = QVBoxLayout()
        groups_col.setSpacing(4)
        groups_col.setContentsMargins(0, 0, 0, 0)

        # --- Transform group (2×2) ---
        transform_grp = QGroupBox("Transform")
        transform_grp.setStyleSheet(_GROUP_STYLE)
        t_vbox = QVBoxLayout(transform_grp)
        t_vbox.setContentsMargins(6, 2, 6, 4)
        t_vbox.setSpacing(2)

        t_row1 = QHBoxLayout(); t_row1.setSpacing(4)
        self._height_sb = self._make_spin(t_row1, "Height", 32, 8192, 400, "px",
                                          "Export height in pixels", step=200)
        t_row1.addSpacing(8)
        self._angle_sb  = self._make_spin(t_row1, "Angle",  -180, 180, 0, "°",
                                          "Rotate frame in 15° increments", step=15)
        t_row1.addStretch()

        t_row2 = QHBoxLayout(); t_row2.setSpacing(4)
        self._width_sb  = self._make_spin(t_row2, "Width",    32, 8192, 400, "px",
                                          "Export width in pixels", step=200)
        t_row2.addSpacing(8)
        self._thin_sb   = self._make_spin(t_row2, "Thinning",  0,  100,   0, "px",
                                          "Erode frame inward; enlarges inner hole", step=5)
        t_row2.addStretch()

        t_vbox.addLayout(t_row1)
        t_vbox.addLayout(t_row2)

        # --- Colour group (2×2) ---
        colour_grp = QGroupBox("Colour")
        colour_grp.setStyleSheet(_GROUP_STYLE)
        c_vbox = QVBoxLayout(colour_grp)
        c_vbox.setContentsMargins(6, 2, 6, 4)
        c_vbox.setSpacing(2)

        c_row1 = QHBoxLayout(); c_row1.setSpacing(4)
        self._hue_sb = self._make_spin(c_row1, "Hue",   -180, 180, 0, "",
                                       "Shift hue around the colour wheel", step=15)
        c_row1.addSpacing(8)
        self._val_sb = self._make_spin(c_row1, "Value", -100, 100, 0, "",
                                       "Adjust brightness; negative darkens", step=15)
        c_row1.addStretch()

        c_row2 = QHBoxLayout(); c_row2.setSpacing(4)
        self._int_sb   = self._make_spin(c_row2, "Intensity", -100, 100,   0, "",
                                         "Adjust saturation; negative desaturates", step=15)
        c_row2.addSpacing(8)
        self._alpha_sb = self._make_spin(c_row2, "Alpha",        0, 100, 100, "%",
                                         "Frame opacity; zero is fully transparent", step=5)
        c_row2.addStretch()

        c_vbox.addLayout(c_row1)
        c_vbox.addLayout(c_row2)

        groups_col.addWidget(transform_grp)
        groups_col.addWidget(colour_grp)
        outer.addLayout(groups_col, 1)

        self._reset_btn = IconButton(
            'sponge', QColor(130, 35, 35),
            "Reset all frame controls to defaults"
        )
        self._reset_btn.clicked.connect(self.reset)
        outer.addWidget(self._reset_btn, alignment=Qt.AlignmentFlag.AlignVCenter)

        self._color_debounce = QTimer()
        self._color_debounce.setSingleShot(True)
        self._color_debounce.setInterval(80)
        self._color_debounce.timeout.connect(self._emit)

        self._width_sb.valueChanged.connect(lambda _: self._on_transform_changed())
        self._height_sb.valueChanged.connect(lambda _: self._on_transform_changed())
        self._angle_sb.valueChanged.connect(lambda _: self._on_transform_changed())
        self._thin_sb.valueChanged.connect(lambda _: self._on_transform_changed())
        self._hue_sb.valueChanged.connect(lambda _: self._on_color_changed())
        self._val_sb.valueChanged.connect(lambda _: self._on_color_changed())
        self._int_sb.valueChanged.connect(lambda _: self._on_color_changed())
        self._alpha_sb.valueChanged.connect(lambda _: self._on_color_changed())

    # ------------------------------------------------------------------

    def _make_spin(self, layout, name: str, lo: int, hi: int,
                   default: int, suffix: str, tooltip: str,
                   step: int = 1) -> QSpinBox:
        lbl = QLabel(name + ":")
        lbl.setStyleSheet("color: #999; font-size: 10px;")
        layout.addWidget(lbl)

        minus_btn = QPushButton("−")
        minus_btn.setFixedSize(22, 22)
        minus_btn.setStyleSheet(_STEP_BTN_STYLE)
        layout.addWidget(minus_btn)

        sb = QSpinBox()
        sb.setRange(lo, hi)
        sb.setValue(default)
        sb.setSuffix(suffix)
        sb.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        sb.setMinimumWidth(36)
        sb.setSingleStep(step)
        sb.setStyleSheet(
            "QSpinBox { background: #333; color: #ccc; border: 1px solid #555;"
            " padding: 1px 4px; font-size: 10px; }"
        )
        sb.setToolTip(tooltip)
        layout.addWidget(sb)

        plus_btn = QPushButton("+")
        plus_btn.setFixedSize(22, 22)
        plus_btn.setStyleSheet(_STEP_BTN_STYLE)
        layout.addWidget(plus_btn)

        minus_btn.clicked.connect(sb.stepDown)
        plus_btn.clicked.connect(sb.stepUp)

        return sb

    def _on_transform_changed(self):
        self._emit()

    def _on_color_changed(self):
        self._color_debounce.start()

    def _emit(self):
        self.frame_params_changed.emit(
            self._width_sb.value(),
            self._height_sb.value(),
            float(self._angle_sb.value()),
            self._thin_sb.value(),
            self._hue_sb.value(),
            self._val_sb.value(),
            self._int_sb.value(),
            self._alpha_sb.value(),
        )

    def reset(self):
        d = self._DEFAULTS
        for sb, key in [
            (self._width_sb,  'width'),     (self._height_sb, 'height'),
            (self._angle_sb,  'angle'),     (self._thin_sb,   'thinning'),
            (self._hue_sb,    'hue'),       (self._val_sb,    'value'),
            (self._int_sb,    'intensity'), (self._alpha_sb,  'alpha'),
        ]:
            sb.blockSignals(True)
            sb.setValue(d[key])
            sb.blockSignals(False)

    def set_params(self, out_width: int, out_height: int, rotation: float,
                   thinning: int, hue: int, value: int, intensity: int, alpha: int):
        all_sbs = [self._width_sb, self._height_sb, self._angle_sb, self._thin_sb,
                   self._hue_sb, self._val_sb, self._int_sb, self._alpha_sb]
        for sb in all_sbs:
            sb.blockSignals(True)
        self._width_sb.setValue(out_width)
        self._height_sb.setValue(out_height)
        self._angle_sb.setValue(int(round(rotation)))
        self._thin_sb.setValue(int(thinning))
        self._hue_sb.setValue(int(hue))
        self._val_sb.setValue(int(value))
        self._int_sb.setValue(int(intensity))
        self._alpha_sb.setValue(int(alpha))
        for sb in all_sbs:
            sb.blockSignals(False)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _int_dialog(title, label, value, lo, hi):
    from PyQt6.QtWidgets import QInputDialog
    return QInputDialog.getInt(None, title, label, value, lo, hi)

def _float_dialog(title, label, value, lo, hi):
    from PyQt6.QtWidgets import QInputDialog
    return QInputDialog.getDouble(None, title, label, value, lo, hi, 2)

def _make_dspin(lo, hi, val, step=1.0):
    s = QDoubleSpinBox()
    s.setRange(lo, hi); s.setSingleStep(step); s.setValue(val)
    return s
