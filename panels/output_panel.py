import os
import numpy as np
from PIL import Image, ImageDraw

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QInputDialog, QSizePolicy, QMessageBox,
)
from PIL import ImageFilter
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPixmap, QImage, QFont

PREVIEW_SIZE = 400   # exported token and live preview are both this many pixels square


# ------------------------------------------------------------------
# Image conversion utilities
# ------------------------------------------------------------------

def _qimage_to_pil(qimage: QImage) -> Image.Image:
    """Convert a QImage to a PIL RGBA Image by reading the raw pixel buffer.

    Forces RGBA8888 format first so the byte layout is always predictable
    regardless of which QImage format was used originally.
    """
    qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimage.width(), qimage.height()
    ptr = qimage.bits()
    ptr.setsize(h * w * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()
    return Image.fromarray(arr, 'RGBA')


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    """Convert a PIL RGBA Image to a QPixmap via a temporary QImage."""
    pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    qimage = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def _outer_mask_from_frame(frame_pil: Image.Image) -> Image.Image:
    """Derive a greyscale mask that is 255 inside the frame's outer boundary and 0 outside.

    Strategy:
      1. Convert the frame alpha to a binary black/white image (white = opaque frame pixels).
      2. Add a 1-pixel black border so the flood fill has guaranteed entry from every edge.
      3. Flood-fill from the top-left corner with a sentinel grey value.
         The fill propagates through all black (transparent) pixels reachable from
         the exterior without crossing any opaque frame pixel.
      4. Pixels still black after the fill are inside the frame's inner hole — they
         should remain visible (backgrounds/figures show through the hole).
      5. Build the final mask: grey (exterior) → 0, everything else → 255.

    Falls back to a fully-opaque mask on any error so rendering never crashes.
    """
    try:
        w, h  = frame_pil.size
        alpha = frame_pil.convert('RGBA').split()[3]

        # White = opaque frame pixel, black = transparent
        binary = Image.new('RGB', (w, h), 'black')
        binary.paste('white', mask=alpha.point(lambda x: 255 if x > 5 else 0))

        # Surround with a 1-px black border so the corner is always reachable
        bordered = Image.new('RGB', (w + 2, h + 2), 'black')
        bordered.paste(binary, (1, 1))

        # Mark all exterior-connected transparent pixels as grey
        SENTINEL = (128, 128, 128)
        ImageDraw.floodfill(bordered, (0, 0), SENTINEL, thresh=10)

        bordered = bordered.crop((1, 1, w + 1, h + 1))

        data    = np.array(bordered)
        outside = (data[:, :, 0] == 128) & (data[:, :, 1] == 128) & (data[:, :, 2] == 128)
        result  = np.where(outside, 0, 255).astype(np.uint8)

        # Erode the mask by 3 pixels so antialiased outer-edge pixels are covered.
        # The 255 region is one connected blob (frame ring + interior hole), so
        # erosion only shrinks the outer boundary — the inner edge is unaffected.
        mask = Image.fromarray(result, mode='L')
        mask = mask.filter(ImageFilter.MinFilter(3))
        mask = mask.filter(ImageFilter.MinFilter(3))
        mask = mask.filter(ImageFilter.MinFilter(3))
        return mask

    except Exception:
        return Image.new('L', frame_pil.size, 255)


# ------------------------------------------------------------------
# Preview widget
# ------------------------------------------------------------------

class PreviewWidget(QWidget):
    """Live 400×400 preview of the current token, clipped to the selected frame boundary.

    A QTimer fires every 100 ms.  On each tick a dirty flag is checked; if the
    scene has changed since the last render, a new composite is generated.
    The dirty flag is set by connecting to QGraphicsScene.changed.

    Rendering pipeline (each dirty tick):
      1. Render the full scene into a 400×400 QImage, cropped to the frame's
         axis-aligned bounding box in scene space.
      2. Render a second QImage containing only the frame item (all other items
         are hidden during this off-screen pass then immediately restored).
      3. Use _outer_mask_from_frame() to derive the exterior clip mask.
      4. Apply the mask to the composite so anything outside the frame is transparent.
      5. Paint a checkerboard then blit the result.
    """

    def __init__(self, scene, parent=None):
        """Connect to the scene's changed signal and start the render timer.

        Args:
            scene: The WorkspaceScene whose items will be composited.
        """
        super().__init__(parent)
        self._scene = scene
        self._frame_item = None
        self._pixmap: QPixmap | None = None
        self._dirty = True
        # Cache: key is (frame.path, *frame.get_params()); value is (frame_pil, outer_mask).
        # Avoids re-rendering the frame and recomputing the mask when only non-frame
        # items have moved.
        self._frame_render_cache: tuple | None = None
        self._frame_render_cache_key: tuple | None = None

        self.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)

        # Only mark dirty when an interaction finishes (mouse release, add, remove)
        # rather than on every scene.changed tick during a drag.
        scene.interaction_ended.connect(self._mark_dirty)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

    def update_frame(self, frame_item):
        """Called when the active frame changes (or is cleared).

        Args:
            frame_item: A TokenItem, or None if no frame is loaded.
        """
        self._frame_item = frame_item
        self._frame_render_cache     = None
        self._frame_render_cache_key = None
        self._mark_dirty()

    def _mark_dirty(self):
        """Flag the preview as needing a re-render on the next timer tick."""
        self._dirty = True

    def _tick(self):
        """Re-render the preview if the scene has changed since the last frame."""
        if self._dirty:
            self._dirty = False
            self._render()

    def _render(self):
        """Composite the scene into a masked 400×400 PIL image and store it as a QPixmap.

        If no frame is selected the pixmap is set to None so paintEvent draws
        the placeholder instead.
        """
        if self._frame_item is None or not self._frame_item.scene():
            self._pixmap = None
            self.update()
            return

        pil = self._composite_at_size(PREVIEW_SIZE)
        if pil is None:
            self._pixmap = None
        else:
            self._pixmap = _pil_to_qpixmap(pil)
        self.update()

    def render_token(self) -> 'Image.Image | None':
        """Render and return the current token as a PIL RGBA image for saving to disk.

        Returns None if no frame is currently selected.
        """
        if self._frame_item is None or not self._frame_item.scene():
            return None
        return self._composite_at_size(PREVIEW_SIZE)

    def _composite_at_size(self, size: int) -> 'Image.Image | None':
        """Render the scene and apply the frame mask, returning a PIL RGBA image.

        Args:
            size: Width and height of the output square in pixels.

        Returns:
            A masked PIL Image, or None if the frame bounding rect is empty.
        """
        frame = self._frame_item
        frame_scene_rect = frame.mapToScene(frame.boundingRect()).boundingRect()
        if frame_scene_rect.isEmpty():
            return None

        target = QRectF(0, 0, size, size)

        # --- Pass 1: full scene composite ---
        full_img = QImage(size, size, QImage.Format.Format_ARGB32)
        full_img.fill(Qt.GlobalColor.transparent)
        p = QPainter(full_img)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self._scene.render(p, target, frame_scene_rect)
        p.end()

        # --- Pass 2: frame-only render for mask extraction (cached) ---
        # The frame's visual output and derived mask only change when its own
        # parameters change.  Skip the expensive show/hide scene render on hits.
        cache_key = (frame.path,) + frame.get_params()
        if cache_key == self._frame_render_cache_key:
            frame_pil, outer_mask = self._frame_render_cache
        else:
            frame_img = QImage(size, size, QImage.Format.Format_ARGB32)
            frame_img.fill(Qt.GlobalColor.transparent)
            hidden = [i for i in self._scene.items() if i is not frame]
            for i in hidden:
                i.setVisible(False)
            try:
                p2 = QPainter(frame_img)
                p2.setRenderHints(
                    QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                )
                self._scene.render(p2, target, frame_scene_rect)
                p2.end()
            finally:
                for i in hidden:
                    i.setVisible(True)
            frame_pil  = _qimage_to_pil(frame_img)
            outer_mask = _outer_mask_from_frame(frame_pil)
            self._frame_render_cache     = (frame_pil, outer_mask)
            self._frame_render_cache_key = cache_key

        # --- Apply mask ---
        composite = _qimage_to_pil(full_img)

        r, g, b, a = composite.split()
        clipped_a  = Image.fromarray(
            np.minimum(np.array(a), np.array(outer_mask)), mode='L'
        )
        return Image.merge('RGBA', (r, g, b, clipped_a))

    # ------------------------------------------------------------------
    # Qt paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        """Paint a checkerboard background (transparency indicator) then the composited pixmap.

        When no frame is selected the widget shows a solid blue rectangle with
        a 'No Frame Selected' label instead.
        """
        painter = QPainter(self)

        if self._pixmap:
            self._draw_checkerboard(painter)
            painter.drawPixmap(0, 0, self._pixmap)
        else:
            painter.fillRect(self.rect(), QColor(30, 80, 160))
            painter.setPen(QPen(QColor(130, 170, 255)))
            painter.setFont(QFont("Arial", 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No Frame Selected")

        painter.end()

    def _draw_checkerboard(self, painter: QPainter):
        """Draw a light-grey checkerboard pattern to indicate transparent areas."""
        tile = 10
        for y in range(0, PREVIEW_SIZE, tile):
            for x in range(0, PREVIEW_SIZE, tile):
                color = QColor(200, 200, 200) if (x // tile + y // tile) % 2 == 0 \
                        else QColor(160, 160, 160)
                painter.fillRect(x, y, tile, tile, color)


# ------------------------------------------------------------------
# Session memory entry
# ------------------------------------------------------------------

class SessionEntry(QWidget):
    """A clickable row in the session memory list showing a thumbnail and the token name.

    Clicking the row emits restore_requested so the main window can reload the
    saved workspace state without this widget needing any direct scene access.
    """

    restore_requested = pyqtSignal(list)  # emits the saved workspace state list

    def __init__(self, pixmap: QPixmap, name: str, state: list, parent=None):
        """Store the workspace state and display a small thumbnail with a name label.

        Args:
            pixmap: The 400×400 token image rendered at print time.
            name:   The filename stem used when the token was saved.
            state:  Workspace state list (from WorkspaceScene.get_workspace_state).
        """
        super().__init__(parent)
        self.state = state
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        thumb = QLabel()
        thumb.setFixedSize(56, 56)
        thumb.setPixmap(
            pixmap.scaled(56, 56, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        )
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("background: #2a2a2a; border: 1px solid #444;")

        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color: #bbb; font-size: 10px;")
        name_lbl.setWordWrap(True)

        layout.addWidget(thumb)
        layout.addWidget(name_lbl)
        self.setStyleSheet(
            "SessionEntry { background: #252525; border: 1px solid #3a3a3a; border-radius: 3px; }"
        )

    def mousePressEvent(self, event):
        """Emit the saved workspace state when the user clicks this entry."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.restore_requested.emit(self.state)


# ------------------------------------------------------------------
# Output panel
# ------------------------------------------------------------------

class OutputPanel(QWidget):
    """The right panel containing the Print button, live preview, and scrollable session memory.

    Owns the PreviewWidget and coordinates printing: asking for a filename,
    saving the PNG, and adding a new SessionEntry to the session list.
    """

    print_requested  = pyqtSignal()   # wired to the Print button
    restore_requested = pyqtSignal(list)  # forwarded from SessionEntry clicks

    def __init__(self, scene, tokens_dir: str, parent=None):
        """Build the panel layout and wire the Print button.

        Args:
            scene:      The WorkspaceScene, passed through to PreviewWidget.
            tokens_dir: Absolute path to the Tokens output folder.
        """
        super().__init__(parent)
        self._tokens_dir = tokens_dir
        self._last_figure_name = "token"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Print button
        self.print_btn = QPushButton("Print")
        self.print_btn.setFixedHeight(30)
        self.print_btn.setStyleSheet(
            "QPushButton { background: #27ae60; color: white; font-weight: bold;"
            " border: none; border-radius: 3px; }"
            "QPushButton:hover { background: #2ecc71; }"
        )
        self.print_btn.clicked.connect(self.print_requested)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.print_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Live preview
        preview_lbl = QLabel("Preview")
        preview_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_lbl.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(preview_lbl)

        self.preview = PreviewWidget(scene)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Session memory
        session_lbl = QLabel("Session Memory")
        session_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        session_lbl.setStyleSheet("color: #888; font-size: 10px; margin-top: 6px;")
        layout.addWidget(session_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: 1px solid #3a3a3a; background: #1c1c1c;")

        self._session_container = QWidget()
        self._session_layout = QVBoxLayout(self._session_container)
        self._session_layout.setContentsMargins(4, 4, 4, 4)
        self._session_layout.setSpacing(4)
        self._session_layout.addStretch()

        scroll.setWidget(self._session_container)
        layout.addWidget(scroll)

        self.setMinimumWidth(PREVIEW_SIZE + 24)

    # ------------------------------------------------------------------
    # Public helpers called by MainWindow
    # ------------------------------------------------------------------

    def set_last_figure(self, filename: str):
        """Update the default token name to match the most recently activated figure.

        Args:
            filename: The basename of the figure file (extension included).
        """
        self._last_figure_name = os.path.splitext(filename)[0]

    def save_token(self, pil_image: Image.Image, workspace_state: list):
        """Ask the user for a filename, save the token PNG, and add a session memory entry.

        The default name is pre-filled from the most recently activated figure.
        If the user cancels the dialog the token is not saved.

        Args:
            pil_image:       RGBA PIL Image from PreviewWidget.render_token().
            workspace_state: Serialised state list from WorkspaceScene.get_workspace_state().
        """
        name, ok = QInputDialog.getText(
            self, "Save Token", "Token name:", text=self._last_figure_name
        )
        if not ok or not name.strip():
            return

        name = name.strip()
        os.makedirs(self._tokens_dir, exist_ok=True)
        path = os.path.join(self._tokens_dir, f"{name}.png")

        try:
            pil_image.save(path, 'PNG')
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", f"Could not save token:\n{e}")
            return

        # Prepend the new entry to the top of the session list (above the stretch)
        pixmap = _pil_to_qpixmap(pil_image)
        entry = SessionEntry(pixmap, name, workspace_state)
        entry.restore_requested.connect(self.restore_requested)
        self._session_layout.insertWidget(0, entry)
