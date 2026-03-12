import math
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsObject, QMenu,
    QDialog, QFormLayout, QSpinBox, QDoubleSpinBox, QDialogButtonBox,
    QGraphicsItem,
)
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal, QSizeF
from PyQt6.QtGui import (
    QPainter, QPen, QBrush, QColor, QPixmap, QTransform, QPainterPath,
)
from panels.utils import load_pixmap

GRID_SIZE = 40
HANDLE_SIZE = 9
ROTATE_OFFSET = 28   # pixels above top edge where rotation handle sits
LAYER_BG = -5
LAYER_FIG = 0
LAYER_FRAME = 5

# Handle name -> (anchor_x, anchor_y) in normalized item rect coords
# anchor 0=left/top, 0.5=center, 1=right/bottom
_SCALE_HANDLES = {
    'tl': (0, 0), 't': (0.5, 0), 'tr': (1, 0),
    'l':  (0, 0.5),              'r':  (1, 0.5),
    'bl': (0, 1), 'b': (0.5, 1), 'br': (1, 1),
}


def _dot(a: QPointF, b: QPointF) -> float:
    """Dot product of two QPointF vectors."""
    return a.x() * b.x() + a.y() * b.y()

def _norm(v: QPointF) -> QPointF:
    """Return v normalised to unit length, or (1,0) if v is near-zero."""
    mag = math.sqrt(v.x() ** 2 + v.y() ** 2)
    return QPointF(v.x() / mag, v.y() / mag) if mag > 1e-9 else QPointF(1.0, 0.0)


class TokenItem(QGraphicsObject):
    """A single image placed in the workspace (background, figure, or frame).

    Renders its pixmap and, when selected, overlays eight scale handles
    (corners + edge midpoints) and one rotation handle above the top edge.
    All transforms (scale, rotation) are stored explicitly so they can be
    serialised and restored for session memory.
    """

    removal_requested = pyqtSignal(object)  # emits self when "Remove" is chosen

    def __init__(self, pixmap: QPixmap, path: str, category: str, layer: int):
        """Initialise a token item.

        Args:
            pixmap:   The source image to display.
            path:     Absolute file path; used as a unique key and for restoration.
            category: One of 'Backgrounds', 'Figures', or 'Frames'.
            layer:    Initial Z-value controlling paint order.
        """
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

        # A small proxy pixmap used during drag so the scene redraws cheaply.
        # At drag-end we swap back to the full-res original.
        self._drag_pixmap = self._make_drag_pixmap(pixmap)
        self._active_pixmap = pixmap   # what paint() draws; swapped during drag

        self.setZValue(layer)
        # transformOriginPoint is used by setRotation() to determine the pivot.
        # Centering it means the image rotates around its own centre.
        self.setTransformOriginPoint(w / 2, h / 2)
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        self.setAcceptHoverEvents(True)
        self._apply_transform()

        # Drag state — populated at the start of each handle drag
        self._active_handle: str | None = None
        self._drag_start_sx = 1.0
        self._drag_start_sy = 1.0
        self._drag_start_rot = 0.0
        self._drag_center_scene = QPointF()
        # Scale drags use scene-space projections onto the item's local axes so
        # that the coordinate system shifting as sx/sy change doesn't cause flicker.
        self._drag_x_axis = QPointF(1.0, 0.0)   # normalised local X in scene space
        self._drag_y_axis = QPointF(0.0, 1.0)   # normalised local Y in scene space
        self._drag_start_dist_x = 1.0            # signed projection of start pos onto X axis
        self._drag_start_dist_y = 1.0            # signed projection of start pos onto Y axis

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------

    def _set_smooth_rendering(self, smooth: bool) -> None:
        """Toggle SmoothPixmapTransform on every view that contains this scene.

        Bicubic filtering looks great at rest but is expensive on every repaint
        during a drag.  Disabling it while the mouse is held and re-enabling on
        release gives a large framerate boost with no visible quality trade-off
        (the proxy pixmap is already lower-res during the drag anyway).
        """
        if self.scene():
            hint = QPainter.RenderHint.SmoothPixmapTransform
            for view in self.scene().views():
                view.setRenderHint(hint, smooth)

    def _make_drag_pixmap(self, pixmap: QPixmap, max_size: int = 512) -> QPixmap:
        """Return a scaled-down copy of pixmap for use during drag operations.

        Rendering a 512 px proxy instead of the original (which may be several
        thousand pixels) cuts per-frame paint cost dramatically.  If the source
        is already small enough, the original is returned unchanged so there is
        no quality loss for small images.
        """
        if pixmap.width() <= max_size and pixmap.height() <= max_size:
            return pixmap
        return pixmap.scaled(
            max_size, max_size,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )

    def _apply_transform(self):
        """Rebuild the item's QTransform from the stored _sx/_sy/_rotation_deg values.

        Scale is applied via setTransform() using a translate-scale-untranslate
        sequence so that the image scales from its centre rather than its
        top-left corner.  Rotation is applied separately via setRotation(),
        which also pivots around transformOriginPoint (the centre).
        """
        w, h = self._pw, self._ph
        t = QTransform()
        t.translate(w / 2, h / 2)
        t.scale(self._sx, self._sy)
        t.translate(-w / 2, -h / 2)
        self.setTransform(t)
        self.setRotation(self._rotation_deg)

    @property
    def layer(self) -> int:
        """The integer Z-value that controls paint order relative to other items."""
        return self._layer

    @layer.setter
    def layer(self, value: int):
        """Set a new Z-value and sync it to Qt's own zValue so rendering updates immediately."""
        self._layer = value
        self.setZValue(value)

    # ------------------------------------------------------------------
    # Bounding rect and shape
    # ------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        """Return the bounding rect that Qt uses for hit-testing and dirty-region tracking.

        Expands the raw pixmap rect outward to include the handle squares and
        the rotation handle that floats above the top edge.  All handle drawing
        and mouse hit-testing is consistent with this expanded rect.
        """
        return QRectF(0, 0, self._pw, self._ph).adjusted(
            -HANDLE_SIZE, -HANDLE_SIZE - ROTATE_OFFSET,
            HANDLE_SIZE, HANDLE_SIZE
        )

    def _item_rect(self) -> QRectF:
        """Return the tight pixmap rect in local (pre-transform) coordinates.

        Used internally wherever we need the actual image boundary rather than
        the inflated bounding rect that includes handles.
        """
        return QRectF(0, 0, self._pw, self._ph)

    # ------------------------------------------------------------------
    # Handle geometry (in local / pre-transform coords)
    # ------------------------------------------------------------------

    def _handle_center(self, name: str) -> QPointF:
        """Return the centre point of a named handle in local (pre-transform) coordinates.

        Scale handles ('tl', 't', 'tr', 'l', 'r', 'bl', 'b', 'br') sit on the
        corners and edge midpoints of the pixmap rect.  The rotation handle
        ('rot') sits directly above the top-centre edge by ROTATE_OFFSET pixels.
        """
        r = self._item_rect()
        if name == 'rot':
            return QPointF(r.width() / 2, -ROTATE_OFFSET)
        ax, ay = _SCALE_HANDLES[name]
        return QPointF(r.x() + r.width() * ax, r.y() + r.height() * ay)

    def _handle_rect(self, name: str) -> QRectF:
        """Return the clickable square QRectF for a named handle, centred on its anchor point."""
        c = self._handle_center(name)
        s = HANDLE_SIZE
        return QRectF(c.x() - s / 2, c.y() - s / 2, s, s)

    def _hit_handle(self, local_pos: QPointF) -> str | None:
        """Return the name of the handle under local_pos, or None if none is hit.

        Handles are only active when the item is selected.  Each handle rect is
        expanded by 2 px on all sides to make small handles easier to grab.
        """
        if not self.isSelected():
            return None
        for name in list(_SCALE_HANDLES.keys()) + ['rot']:
            if self._handle_rect(name).adjusted(-14, -14, 14, 14).contains(local_pos):
                return name
        return None

    # ------------------------------------------------------------------
    # Paint
    # ------------------------------------------------------------------

    def paint(self, painter: QPainter, option, widget=None):
        """Draw the pixmap, and when selected overlay the selection border and transform handles.

        painter operates in local (pre-transform) coordinates.  Qt applies the
        item's QTransform automatically before calling this method, so
        coordinates used here map directly to the pixmap's natural dimensions.
        """
        r = self._item_rect()
        # Draw at the item's fixed logical dimensions so the proxy and the
        # full-res pixmap both fill exactly the same space on screen.
        painter.drawPixmap(0, 0, self._pw, self._ph, self._active_pixmap)

        if self.isSelected():
            painter.save()
            # Dashed selection border
            painter.setPen(QPen(QColor(0, 140, 255), 1.5, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(r)

            # Stem line connecting the top-centre edge to the rotation handle
            cx = r.width() / 2
            painter.setPen(QPen(QColor(0, 200, 100), 1))
            painter.drawLine(QPointF(cx, 0), QPointF(cx, -ROTATE_OFFSET))

            # Scale handles — white squares at corners and edge midpoints
            painter.setPen(QPen(QColor(0, 100, 200), 1))
            painter.setBrush(QBrush(QColor(255, 255, 255, 210)))
            for name in _SCALE_HANDLES:
                painter.drawRect(self._handle_rect(name))

            # Rotation handle — green circle above the top edge
            painter.setPen(QPen(QColor(0, 160, 80), 1))
            painter.setBrush(QBrush(QColor(0, 220, 100, 200)))
            painter.drawEllipse(self._handle_rect('rot'))

            painter.restore()

    # ------------------------------------------------------------------
    # Mouse events
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Begin a handle drag if the click lands on a handle; otherwise fall through to Qt's move handler.

        When a handle is hit, we snapshot the current transform state so that
        mouseMoveEvent can compute deltas relative to the drag origin rather
        than accumulating floating-point drift across frames.
        """
        if event.button() == Qt.MouseButton.LeftButton:
            # Switch to proxy pixmap and fast rendering for the drag duration.
            self._active_pixmap = self._drag_pixmap
            self._set_smooth_rendering(False)
            handle = self._hit_handle(event.pos())
            if handle:
                self._active_handle = handle
                self._drag_start_sx  = self._sx
                self._drag_start_sy  = self._sy
                self._drag_start_rot = self._rotation_deg

                # Scene-space centre — stays fixed during a centre-scale drag
                # because both edges move symmetrically.
                cx = self._pw / 2
                cy = self._ph / 2
                self._drag_center_scene = self.mapToScene(QPointF(cx, cy))

                # Capture the item's local axes in scene space NOW (before any
                # scale change) so mouseMoveEvent can project onto them stably.
                origin = self.mapToScene(QPointF(0.0, 0.0))
                self._drag_x_axis = _norm(self.mapToScene(QPointF(1.0, 0.0)) - origin)
                self._drag_y_axis = _norm(self.mapToScene(QPointF(0.0, 1.0)) - origin)

                # Signed start distances from centre along each local axis.
                start_offset = event.scenePos() - self._drag_center_scene
                self._drag_start_dist_x = _dot(start_offset, self._drag_x_axis)
                self._drag_start_dist_y = _dot(start_offset, self._drag_y_axis)

                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Update scale or rotation while a handle drag is in progress.

        Rotation: uses the angle between the drag-start vector and the current
        mouse vector (both measured from the item's scene-space centre), so the
        handle appears to stay under the cursor regardless of initial offset.

        Scale: computes the change relative to the drag-start position in local
        coordinates.  Dragging a corner affects both axes; an edge handle
        affects only the perpendicular axis.  Scale is clamped to 0.05 to
        prevent the item from collapsing to zero or flipping.
        """
        if self._active_handle:
            handle = self._active_handle

            if handle == 'rot':
                center = self._drag_center_scene
                sv = event.scenePos() - center   # use scene pos directly; no local needed
                pv = self.mapToScene(
                    QPointF(self._pw / 2, 0)
                ) - center                        # fixed "up" direction at drag start
                # Compute angle between the "top" direction and current mouse
                base_a  = math.atan2(-pv.y(), pv.x())   # scene Y is flipped vs maths Y
                curr_a  = math.atan2(-sv.y(), sv.x())
                self._rotation_deg = self._drag_start_rot + math.degrees(curr_a - base_a)
                self._apply_transform()
            else:
                # Project the current mouse position onto the item's local axes
                # (captured at drag-start and held fixed).  This avoids the
                # flicker caused by local coords shifting as sx/sy change.
                curr_offset = event.scenePos() - self._drag_center_scene
                curr_dx = _dot(curr_offset, self._drag_x_axis)
                curr_dy = _dot(curr_offset, self._drag_y_axis)

                sx, sy = self._drag_start_sx, self._drag_start_sy

                if ('r' in handle or 'l' in handle) and abs(self._drag_start_dist_x) > 0.5:
                    sx = max(0.05, self._drag_start_sx * curr_dx / self._drag_start_dist_x)

                if ('b' in handle or 't' in handle) and handle != 'rot' and abs(self._drag_start_dist_y) > 0.5:
                    sy = max(0.05, self._drag_start_sy * curr_dy / self._drag_start_dist_y)

                self._sx, self._sy = sx, sy
                self._apply_transform()

            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End an active handle drag, restore the full-res pixmap, and return to normal interaction mode."""
        self._active_handle = None
        # Restore full-res pixmap and smooth rendering now that movement has stopped.
        self._active_pixmap = self._pixmap
        self._set_smooth_rendering(True)
        self.update()
        if self.scene():
            self.scene().interaction_ended.emit()
        super().mouseReleaseEvent(event)

    def hoverMoveEvent(self, event):
        """Update the cursor shape to hint at the action each handle will perform.

        Corner handles show a diagonal resize cursor, edge handles show an
        axis-aligned resize cursor, and the rotation handle shows a crosshair.
        The cursor resets to the default arrow when not over any handle.
        """
        handle = self._hit_handle(event.pos())
        cursors = {
            'tl': Qt.CursorShape.SizeFDiagCursor,
            'tr': Qt.CursorShape.SizeBDiagCursor,
            'bl': Qt.CursorShape.SizeBDiagCursor,
            'br': Qt.CursorShape.SizeFDiagCursor,
            't':  Qt.CursorShape.SizeVerCursor,
            'b':  Qt.CursorShape.SizeVerCursor,
            'l':  Qt.CursorShape.SizeHorCursor,
            'r':  Qt.CursorShape.SizeHorCursor,
            'rot': Qt.CursorShape.CrossCursor,
        }
        self.setCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor))

    def hoverLeaveEvent(self, event):
        """Reset the cursor when the pointer leaves this item's bounding rect."""
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def contextMenuEvent(self, event):
        """Show a right-click context menu for precise numeric transform control and removal.

        Provides actions for setting layer, position, scale, and rotation via
        dialogs, plus a 'Remove from Workspace' action that emits removal_requested
        so the scene can clean up its bookkeeping without the item needing a
        direct reference back to the scene.
        """
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
            if ok:
                self.layer = val
        elif action == pos_act:
            self._show_pos_dialog()
        elif action == scale_act:
            self._show_scale_dialog()
        elif action == rot_act:
            val, ok = _float_dialog("Set Rotation", "Degrees:", self._rotation_deg, -360, 360)
            if ok:
                self._rotation_deg = val
                self._apply_transform()
        elif action == remove_act:
            self.removal_requested.emit(self)

    def _show_pos_dialog(self):
        """Open a dialog that lets the user type exact X/Y scene coordinates for this item."""
        dlg = QDialog()
        dlg.setWindowTitle("Set Position")
        form = QFormLayout(dlg)
        xs = _make_dspin(-100000, 100000, self.x())
        ys = _make_dspin(-100000, 100000, self.y())
        form.addRow("X:", xs)
        form.addRow("Y:", ys)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec():
            self.setPos(xs.value(), ys.value())

    def _show_scale_dialog(self):
        """Open a dialog that lets the user type exact X and Y scale multipliers.

        Independent X/Y control allows non-uniform stretching that can't be
        achieved as easily with the drag handles alone.
        """
        dlg = QDialog()
        dlg.setWindowTitle("Set Scale")
        form = QFormLayout(dlg)
        sxs  = _make_dspin(0.01, 50, self._sx, step=0.1)
        sys_ = _make_dspin(0.01, 50, self._sy, step=0.1)
        form.addRow("Scale X:", sxs)
        form.addRow("Scale Y:", sys_)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)
        if dlg.exec():
            self._sx, self._sy = sxs.value(), sys_.value()
            self._apply_transform()

    # ------------------------------------------------------------------
    # State serialisation (for session memory)
    # ------------------------------------------------------------------

    def get_state(self) -> dict:
        """Serialise all transform state to a plain dict for in-memory session storage.

        The dict contains everything needed to reconstruct an identical item via
        from_state(), including the source path, category, layer, position,
        rotation, and independent X/Y scale.
        """
        return {
            'path': self.path,
            'category': self.category,
            'layer': self._layer,
            'x': self.x(),
            'y': self.y(),
            'rotation': self._rotation_deg,
            'sx': self._sx,
            'sy': self._sy,
        }

    @staticmethod
    def from_state(state: dict) -> 'TokenItem | None':
        """Reconstruct a TokenItem from a previously serialised state dict.

        Returns None if the source image file can no longer be found or loaded,
        which can happen if files were moved or deleted between prints.
        """
        pixmap = load_pixmap(state['path'], max_size=1024)
        if pixmap.isNull():
            return None
        item = TokenItem(pixmap, state['path'], state['category'], state['layer'])
        item.setPos(state['x'], state['y'])
        item._sx = state['sx']
        item._sy = state['sy']
        item._rotation_deg = state['rotation']
        item._apply_transform()
        return item


# ------------------------------------------------------------------
# Scene
# ------------------------------------------------------------------

class WorkspaceScene(QGraphicsScene):
    """Manages the collection of TokenItems on the canvas.

    Enforces the per-category limits (max 8 figures, max 8 backgrounds, 1 frame),
    tracks which item is the active frame, and emits signals so the output panel
    can update the preview whenever the frame changes or an item is removed.
    """

    frame_changed      = pyqtSignal(object)    # emits TokenItem when frame changes, None when cleared
    item_removed       = pyqtSignal(str, str)  # emits (path, category) after an item is removed
    interaction_ended  = pyqtSignal()          # emits when a drag ends or the item set changes

    def __init__(self):
        """Set up the scene with a large virtual canvas and empty item tracking state."""
        super().__init__()
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self._items: dict[str, TokenItem] = {}  # path -> item
        self._frame: TokenItem | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def frame_item(self) -> 'TokenItem | None':
        """The currently active frame TokenItem, or None if no frame is loaded."""
        return self._frame

    def add_image(self, path: str, category: str) -> bool:
        """Load an image from disk and add it to the workspace, returning False if refused.

        Refuses to add if the per-category limit is already reached (8 figures or
        8 backgrounds).  Adding a new frame automatically removes any existing
        frame first.  The item is spawned centred at the scene origin.
        """
        if path in self._items:
            return True

        # Enforce limits
        figs = sum(1 for i in self._items.values() if i.category == 'Figures')
        bgs  = sum(1 for i in self._items.values() if i.category == 'Backgrounds')
        if category == 'Figures'     and figs >= 8:
            return False
        if category == 'Backgrounds' and bgs  >= 8:
            return False

        # Replace existing frame
        if category == 'Frames' and self._frame is not None:
            self._remove_item(self._frame)

        # SVGs are rasterised to 1024 px on their longest side so they remain
        # sharp when scaled up on the canvas; raster files load at native size.
        pixmap = load_pixmap(path, max_size=1024)
        if pixmap.isNull():
            return False

        layer = {'Backgrounds': LAYER_BG, 'Figures': LAYER_FIG, 'Frames': LAYER_FRAME}[category]
        item = TokenItem(pixmap, path, category, layer)
        item.setPos(-pixmap.width() / 2, -pixmap.height() / 2)

        # Figures and backgrounds often come in at high resolution; spawn them
        # at quarter-size so they don't overwhelm the canvas on first load.
        if category != 'Frames':
            item._sx = 0.25
            item._sy = 0.25
            item._apply_transform()

        item.removal_requested.connect(self._remove_item)

        self.addItem(item)
        self._items[path] = item

        if category == 'Frames':
            self._frame = item
            self.frame_changed.emit(item)

        self.interaction_ended.emit()
        return True

    def remove_image(self, path: str, _category: str):
        """Remove the item associated with path (called when user deselects a thumbnail)."""
        item = self._items.get(path)
        if item:
            self._remove_item(item)

    def clear_all(self):
        """Remove every item from the scene and reset frame tracking state."""
        for item in list(self._items.values()):
            self.removeItem(item)
        self._items.clear()
        if self._frame is not None:
            self._frame = None
            self.frame_changed.emit(None)
        self.interaction_ended.emit()

    def get_active_paths(self) -> set[str]:
        """Return the set of file paths for all items currently in the workspace."""
        return set(self._items.keys())

    def get_workspace_state(self) -> list[dict]:
        """Serialise the current workspace to a list of state dicts, one per item.

        Used by the output panel to snapshot the workspace at print time so that
        session memory entries can restore the exact layout later.
        """
        return [item.get_state() for item in self._items.values()]

    def restore_workspace_state(self, states: list[dict]):
        """Clear the current workspace and rebuild it from a previously captured state list.

        Items are added in layer order (lowest first) so Z-ordering is correct
        before any painting occurs.  Items whose source files can no longer be
        found are silently skipped.
        """
        self.clear_all()
        for state in sorted(states, key=lambda s: s['layer']):
            item = TokenItem.from_state(state)
            if item is None:
                continue
            item.removal_requested.connect(self._remove_item)
            self.addItem(item)
            self._items[state['path']] = item
            if state['category'] == 'Frames':
                self._frame = item
                self.frame_changed.emit(item)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _remove_item(self, item: TokenItem):
        """Internal removal that cleans up tracking dicts and emits the appropriate signals.

        Called both by remove_image() (user deselects thumbnail) and by the
        item's own removal_requested signal (user chooses 'Remove' from context menu).
        """
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
    """Viewport for WorkspaceScene with a grid background, zoom, and middle-click pan."""

    def __init__(self, scene: WorkspaceScene):
        """Configure render quality, interaction modes, and initial background colour."""
        super().__init__(scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QBrush(QColor(70, 70, 70)))

        self._pan_start = None
        self._pan_sb_x = 0
        self._pan_sb_y = 0

    def drawBackground(self, painter: QPainter, rect):
        """Draw the solid grey background and an evenly spaced grid of lines.

        The grid is drawn at GRID_SIZE intervals aligned to world-space
        coordinates, so it stays stationary as the user pans and zooms.
        """
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
        """Zoom in or out centred on the cursor position using the mouse wheel.

        Each wheel step scales the view by 15 %.  The anchor is set to
        AnchorUnderMouse so the point under the cursor stays fixed during zoom.
        """
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, event):
        """Begin a middle-click pan by recording the cursor and scrollbar start positions."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = event.pos()
            self._pan_sb_x  = self.horizontalScrollBar().value()
            self._pan_sb_y  = self.verticalScrollBar().value()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Scroll the view while a middle-click pan is active."""
        if self._pan_start is not None:
            delta = event.pos() - self._pan_start
            self.horizontalScrollBar().setValue(self._pan_sb_x - delta.x())
            self.verticalScrollBar().setValue(self._pan_sb_y - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """End a middle-click pan and restore the normal cursor."""
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_start = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _int_dialog(title, label, value, lo, hi):
    """Show a single-integer input dialog and return (value, accepted) like QInputDialog.getInt."""
    from PyQt6.QtWidgets import QInputDialog
    return QInputDialog.getInt(None, title, label, value, lo, hi)

def _float_dialog(title, label, value, lo, hi):
    """Show a single-float input dialog and return (value, accepted) like QInputDialog.getDouble."""
    from PyQt6.QtWidgets import QInputDialog
    return QInputDialog.getDouble(None, title, label, value, lo, hi, 2)

def _make_dspin(lo, hi, val, step=1.0):
    """Create and return a configured QDoubleSpinBox with the given range, value, and step."""
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    return s
