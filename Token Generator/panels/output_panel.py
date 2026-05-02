import os
import shutil
import base64
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QSizePolicy, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QRectF, QTimer
from PyQt6.QtGui import QPainter, QColor, QBrush, QPen, QPixmap, QImage, QFont

from panels.utils import IconButton

PREVIEW_SIZE = 400


# ------------------------------------------------------------------
# Image conversion utilities
# ------------------------------------------------------------------

def _qimage_to_pil(qimage: QImage) -> Image.Image:
    qimage = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = qimage.width(), qimage.height()
    ptr = qimage.bits()
    ptr.setsize(h * w * 4)
    arr = np.frombuffer(ptr, dtype=np.uint8).reshape((h, w, 4)).copy()
    return Image.fromarray(arr, 'RGBA')


def _pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    pil_img = pil_img.convert('RGBA')
    data = pil_img.tobytes('raw', 'RGBA')
    qimage = QImage(data, pil_img.width, pil_img.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def _outer_mask_from_frame(frame_pil: Image.Image) -> Image.Image:
    """Derive a greyscale mask: 255 inside the frame's outer boundary, 0 outside."""
    try:
        w, h  = frame_pil.size
        alpha = frame_pil.convert('RGBA').split()[3]
        binary = Image.new('RGB', (w, h), 'black')
        binary.paste('white', mask=alpha.point(lambda x: 255 if x > 5 else 0))
        bordered = Image.new('RGB', (w + 2, h + 2), 'black')
        bordered.paste(binary, (1, 1))
        SENTINEL = (128, 128, 128)
        ImageDraw.floodfill(bordered, (0, 0), SENTINEL, thresh=10)
        bordered = bordered.crop((1, 1, w + 1, h + 1))
        data    = np.array(bordered)
        outside = (data[:, :, 0] == 128) & (data[:, :, 1] == 128) & (data[:, :, 2] == 128)
        result  = np.where(outside, 0, 255).astype(np.uint8)
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
    """Live 400×400 preview clipped to the selected frame boundary."""

    def __init__(self, scene, parent=None):
        super().__init__(parent)
        self._scene = scene
        self._frame_item = None
        self._pixmap: QPixmap | None = None
        self._dirty = True
        self._frame_render_cache: tuple | None = None
        self._frame_render_cache_key: tuple | None = None

        self.setFixedSize(PREVIEW_SIZE, PREVIEW_SIZE)
        scene.interaction_ended.connect(self._mark_dirty)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

    def update_frame(self, frame_item):
        self._frame_item = frame_item
        self._frame_render_cache     = None
        self._frame_render_cache_key = None
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True

    def _tick(self):
        if self._dirty:
            self._dirty = False
            self._render()

    def _render(self):
        if self._frame_item is None or not self._frame_item.scene():
            self._pixmap = None
            self.update()
            return
        pil = self._composite_at_size(PREVIEW_SIZE, PREVIEW_SIZE)
        self._pixmap = _pil_to_qpixmap(pil) if pil is not None else None
        self.update()

    def render_token(self, width: int = PREVIEW_SIZE,
                     height: int = PREVIEW_SIZE) -> 'Image.Image | None':
        """Render the token at the requested pixel dimensions."""
        if self._frame_item is None or not self._frame_item.scene():
            return None
        return self._composite_at_size(width, height)

    def _composite_at_size(self, width: int, height: int) -> 'Image.Image | None':
        frame = self._frame_item
        frame_scene_rect = frame.mapToScene(frame.boundingRect()).boundingRect()
        if frame_scene_rect.isEmpty():
            return None

        target = QRectF(0, 0, width, height)

        # Pass 1: full scene composite
        full_img = QImage(width, height, QImage.Format.Format_ARGB32)
        full_img.fill(Qt.GlobalColor.transparent)
        p = QPainter(full_img)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self._scene._is_rendering = True
        self._scene.render(p, target, frame_scene_rect)
        self._scene._is_rendering = False
        p.end()

        # Pass 2: frame-only render (cached by params + dimensions)
        cache_key = (frame.path,) + frame.get_params() + (width, height)
        if cache_key == self._frame_render_cache_key:
            frame_pil, outer_mask = self._frame_render_cache
        else:
            frame_img = QImage(width, height, QImage.Format.Format_ARGB32)
            frame_img.fill(Qt.GlobalColor.transparent)
            hidden = [i for i in self._scene.items() if i is not frame]
            for i in hidden: i.setVisible(False)
            try:
                p2 = QPainter(frame_img)
                p2.setRenderHints(
                    QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
                )
                self._scene._is_rendering = True
                self._scene.render(p2, target, frame_scene_rect)
                self._scene._is_rendering = False
                p2.end()
            finally:
                for i in hidden: i.setVisible(True)
            frame_pil  = _qimage_to_pil(frame_img)
            outer_mask = _outer_mask_from_frame(frame_pil)
            self._frame_render_cache     = (frame_pil, outer_mask)
            self._frame_render_cache_key = cache_key

        # Apply mask
        composite = _qimage_to_pil(full_img)
        if outer_mask.size != composite.size:
            outer_mask = outer_mask.resize(composite.size, Image.LANCZOS)
        r, g, b, a = composite.split()
        clipped_a = Image.fromarray(
            np.minimum(np.array(a), np.array(outer_mask)), mode='L'
        )
        return Image.merge('RGBA', (r, g, b, clipped_a))

    # ------------------------------------------------------------------
    # Qt paint
    # ------------------------------------------------------------------

    def paintEvent(self, event):
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
    """Clickable row in the session memory list; restores workspace + print settings."""

    # Emits (workspace_state, print_settings)
    restore_requested = pyqtSignal(list, dict)

    def __init__(self, pixmap: QPixmap, name: str,
                 state: list, print_settings: dict, parent=None):
        super().__init__(parent)
        self.state = state
        self.print_settings = print_settings
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.restore_requested.emit(self.state, self.print_settings)


# ------------------------------------------------------------------
# Output panel
# ------------------------------------------------------------------

class OutputPanel(QWidget):
    """Right panel: Print button, live preview, and scrollable session memory."""

    print_requested   = pyqtSignal()
    restore_requested = pyqtSignal(list, dict)  # (workspace_state, print_settings)

    def __init__(self, scene, tokens_dir: str, parent=None):
        super().__init__(parent)
        self._tokens_dir = tokens_dir
        self._last_figure_name = "token"
        # Default print settings — persisted across prints within a session
        self._print_settings: dict = {}
        # Paths of tokens printed since the last "throw"
        self._session_token_paths: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        # Top button row: Print (left) + Throw (right)
        btn_row = QHBoxLayout()
        self.print_btn = IconButton(
            'printer', QColor(32, 119, 67),
            "Export current token to chosen folder"
        )
        self.throw_btn = IconButton(
            'throw', QColor(42, 84, 147),
            "Move session tokens to another folder"
        )
        self.print_btn.clicked.connect(self.print_requested)
        self.throw_btn.clicked.connect(self._throw_tokens)
        btn_row.addWidget(self.print_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.throw_btn)
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
    # Public helpers
    # ------------------------------------------------------------------

    def set_last_figure(self, filename: str):
        self._last_figure_name = os.path.splitext(filename)[0]

    def set_tokens_dir(self, path: str):
        self._tokens_dir = path

    def get_print_settings(self) -> dict:
        return dict(self._print_settings)

    def save_token(self, pil_image: Image.Image, workspace_state: list,
                   print_settings: dict):
        """Save the token to disk and add a session memory entry.

        Args:
            pil_image:       Already-rendered PIL RGBA image at the correct size.
            workspace_state: Scene state snapshot.
            print_settings:  Dict with keys name, format, folder, width, height.
        """
        name   = print_settings.get("name", "token").strip() or "token"
        fmt    = print_settings.get("format", "WebP").lower()
        folder = print_settings.get("folder", self._tokens_dir)

        os.makedirs(folder, exist_ok=True)

        ext_map = {"webp": ".webp", "png": ".png", "jpeg": ".jpg", "jpg": ".jpg", "svg": ".svg"}
        ext = ext_map.get(fmt, ".webp")
        path = os.path.join(folder, f"{name}{ext}")

        try:
            if fmt == "svg":
                _save_as_svg(pil_image, path)
            elif fmt in ("jpeg", "jpg"):
                pil_image.convert("RGB").save(path, "JPEG", quality=92)
            elif fmt == "png":
                pil_image.save(path, "PNG")
            else:
                pil_image.save(path, "WEBP", quality=92)
        except Exception as e:
            QMessageBox.warning(self, "Save Failed", f"Could not save token:\n{e}")
            return

        self._session_token_paths.append(path)
        self._print_settings = dict(print_settings)

        # Add session entry (preview thumbnail is always 400×400)
        preview_pil = pil_image
        if pil_image.width != PREVIEW_SIZE or pil_image.height != PREVIEW_SIZE:
            preview_pil = pil_image.resize(
                (PREVIEW_SIZE, PREVIEW_SIZE), Image.LANCZOS
            )
        pixmap = _pil_to_qpixmap(preview_pil)
        entry = SessionEntry(pixmap, name, workspace_state, dict(print_settings))
        entry.restore_requested.connect(self.restore_requested)
        self._session_layout.insertWidget(0, entry)

    # ------------------------------------------------------------------
    # Throw tokens
    # ------------------------------------------------------------------

    def _throw_tokens(self):
        """Move all tokens printed since the last throw to a user-chosen folder."""
        # Filter to paths that still exist
        existing = [p for p in self._session_token_paths if os.path.isfile(p)]
        if not existing:
            QMessageBox.information(
                self, "Nothing to Throw",
                "No tokens have been printed since the last throw."
            )
            return

        dest = QFileDialog_getDir(self, "Choose Destination Folder")
        if not dest:
            return

        os.makedirs(dest, exist_ok=True)
        moved, errors = 0, []
        for src in existing:
            fname = os.path.basename(src)
            dst = os.path.join(dest, fname)
            base, ext = os.path.splitext(dst)
            n = 1
            while os.path.exists(dst):
                dst = f"{base}_{n}{ext}"
                n += 1
            try:
                shutil.move(src, dst)
                moved += 1
            except Exception as e:
                errors.append(f"{fname}: {e}")

        self._session_token_paths.clear()

        msg = f"Moved {moved} token{'s' if moved != 1 else ''} to:\n{dest}"
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors)
        QMessageBox.information(self, "Throw Complete", msg)


# ------------------------------------------------------------------
# SVG export helper
# ------------------------------------------------------------------

def _save_as_svg(pil_image: Image.Image, path: str):
    """Write an SVG that embeds the raster token as a base64 PNG."""
    import io
    buf = io.BytesIO()
    pil_image.save(buf, "PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    w, h = pil_image.size
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}">\n'
        f'  <image href="data:image/png;base64,{b64}" width="{w}" height="{h}"/>\n'
        f'</svg>\n'
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


# ------------------------------------------------------------------
# Thin wrapper so _throw_tokens can call QFileDialog without importing at module level
# ------------------------------------------------------------------

def QFileDialog_getDir(parent, caption: str) -> str:
    from PyQt6.QtWidgets import QFileDialog
    return QFileDialog.getExistingDirectory(parent, caption)
