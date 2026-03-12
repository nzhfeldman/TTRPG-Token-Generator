import os
import subprocess
import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QMenu, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QFont
from panels.utils import load_pixmap

THUMBNAIL_SIZE = 80   # pixels; images are scaled to fit within this square
GLOW_HOVER    = QColor(100, 180, 255)
GLOW_SELECTED = QColor(50, 110, 210)


# ---------------------------------------------------------------------------
# Background-removal worker
# ---------------------------------------------------------------------------

class BgRemoveWorker(QObject):
    """Removes a background by running rembg in a child subprocess via a QThread.

    Running rembg in a QThread directly causes ONNX Runtime to segfault on
    Windows when initialised off the main thread.  Delegating to a subprocess
    fully isolates the neural-net inference: even a hard crash there cannot
    affect our process.

    Saves the result as {original_stem}_nobg.png alongside the source file.
    """

    finished = pyqtSignal(str)   # absolute path to the saved output file
    failed   = pyqtSignal(str)   # human-readable error message

    # Small inline script executed by the child Python interpreter.
    _SCRIPT = (
        "from rembg import remove; from PIL import Image; "
        "img = Image.open({src!r}); "
        "result = remove(img); "
        "result.save({dst!r}, 'PNG')"
    )

    def __init__(self, input_path: str):
        """Args:
            input_path: Absolute path to the source image file.
        """
        super().__init__()
        self.input_path = input_path

    def run(self):
        """Spawn a subprocess that runs rembg and emit finished or failed when done."""
        try:
            stem, _ = os.path.splitext(self.input_path)
            output_path = stem + "_nobg.png"

            script = self._SCRIPT.format(src=self.input_path, dst=output_path)
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=300,   # 5-minute ceiling covers model download on first run
            )

            if result.returncode == 0:
                self.finished.emit(output_path)
            else:
                # Surface the subprocess stderr so the user sees the real error
                msg = result.stderr.strip() or f"Process exited with code {result.returncode}"
                self.failed.emit(msg)

        except subprocess.TimeoutExpired:
            self.failed.emit("Background removal timed out after 5 minutes.")
        except FileNotFoundError:
            self.failed.emit("Could not locate the Python interpreter to run rembg.")
        except Exception as e:
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Thumbnail widget
# ---------------------------------------------------------------------------

class ImageThumbnail(QWidget):
    """A clickable thumbnail widget representing one image file in an input folder.

    Clicking toggles the selected state and emits `clicked` so the column can
    forward the activation/deactivation event up the chain.  Hover and selection
    states are drawn as coloured border glows rather than stylesheet borders so
    the effect is visible against dark backgrounds and semi-transparent PNGs.

    Right-clicking opens a context menu with a 'Remove Background' option that
    runs rembg in a background thread and saves the result alongside the original.
    """

    clicked = pyqtSignal(str, str, bool)  # (path, category, is_now_selected)

    def __init__(self, path: str, category: str, parent=None):
        """Load and scale the image at path, storing it ready for painting.

        Args:
            path:     Absolute path to the image file.
            category: The input folder category ('Backgrounds', 'Figures', 'Frames').
        """
        super().__init__(parent)
        self.path = path
        self.category = category
        self._selected = False
        self._hovered  = False
        self._processing = False   # True while rembg is running

        self.setFixedSize(THUMBNAIL_SIZE + 12, THUMBNAIL_SIZE + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(path))

        # Pre-scale the pixmap once so paint() is fast.
        # SVGs are rasterised at 2× thumbnail size so they look sharp even on
        # high-DPI displays; raster files are loaded at native resolution.
        raw = load_pixmap(path, max_size=THUMBNAIL_SIZE * 2)
        if raw.isNull():
            self._pixmap = None
        else:
            self._pixmap = raw.scaled(
                THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        # Thread/worker references kept alive for the duration of processing
        self._thread: QThread | None = None
        self._worker: BgRemoveWorker | None = None

    # ------------------------------------------------------------------
    # Public helpers called by the column
    # ------------------------------------------------------------------

    def deselect(self):
        """Deselect this thumbnail without emitting the clicked signal."""
        self._selected = False
        self.update()

    @property
    def selected(self) -> bool:
        """Whether this thumbnail is currently in the selected (activated) state."""
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        """Set the selected state directly (used when restoring a session)."""
        self._selected = value
        self.update()

    # ------------------------------------------------------------------
    # Background removal
    # ------------------------------------------------------------------

    def _start_bg_removal(self):
        """Spin up a QThread, move a BgRemoveWorker onto it, and start processing.

        The thumbnail is locked against interaction during processing and shows
        a visual overlay so the user knows something is happening.
        """
        self._processing = True
        self.setCursor(Qt.CursorShape.WaitCursor)
        self.setToolTip("Removing background…")
        self.update()

        self._worker = BgRemoveWorker(self.path)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        # Clean up the thread after either outcome
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.start()

    def _on_finished(self, output_path: str):
        """Restore the thumbnail to its normal state after a successful removal."""
        self._processing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(self.path))
        self.update()
        # The column's 2-second refresh timer will pick up the new _nobg.png file
        # automatically; no manual refresh needed here.

    def _on_failed(self, message: str):
        """Restore normal state and show an error dialog if removal failed."""
        self._processing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(self.path))
        self.update()
        QMessageBox.warning(None, "Background Removal Failed", message)

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        """Draw the border glow, the thumbnail image, and (if processing) a progress overlay.

        The glow is a coloured rounded-rect border: bright blue on hover,
        dimmer blue when selected, neutral dark when neither.  While rembg is
        running a semi-transparent dark overlay with 'Removing BG…' text is
        drawn on top so the user gets clear feedback.
        """
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._selected:
            painter.setPen(QPen(GLOW_SELECTED, 3))
            painter.setBrush(QBrush(QColor(30, 70, 130, 80)))
        elif self._hovered:
            painter.setPen(QPen(GLOW_HOVER, 3))
            painter.setBrush(QBrush(QColor(70, 130, 210, 60)))
        else:
            painter.setPen(QPen(QColor(55, 55, 55), 1))
            painter.setBrush(QBrush(QColor(40, 40, 40)))

        painter.drawRoundedRect(2, 2, self.width() - 4, self.height() - 4, 4, 4)

        if self._pixmap:
            x = (self.width()  - self._pixmap.width())  // 2
            y = (self.height() - self._pixmap.height()) // 2
            painter.drawPixmap(x, y, self._pixmap)

        if self._processing:
            # Semi-transparent overlay with status text
            painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(2, 2, self.width() - 4, self.height() - 4, 4, 4)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Removing\nBG…")

        painter.end()

    def mousePressEvent(self, event):
        """Toggle selection on left click; ignore clicks while processing."""
        if self._processing:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._selected = not self._selected
            self.clicked.emit(self.path, self.category, self._selected)
            self.update()

    def contextMenuEvent(self, event):
        """Show a right-click menu with the Remove Background option.

        The option is disabled while a removal is already in progress to prevent
        launching duplicate threads on the same file.
        """
        menu = QMenu()
        remove_act = menu.addAction("Remove Background")
        remove_act.setEnabled(not self._processing)
        action = menu.exec(event.globalPos())
        if action == remove_act:
            self._start_bg_removal()

    def enterEvent(self, event):
        """Activate the hover glow when the cursor enters the widget."""
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        """Remove the hover glow when the cursor leaves the widget."""
        self._hovered = False
        self.update()


# ---------------------------------------------------------------------------
# Column widget
# ---------------------------------------------------------------------------

class ImageColumn(QWidget):
    """A scrollable, filterable column of ImageThumbnail widgets for one input folder.

    Scans the folder on creation and again every two seconds so newly added
    files appear automatically.  Thumbnails are sorted newest-to-oldest by
    file modification time.
    """

    image_activated   = pyqtSignal(str, str)  # (path, category) when thumbnail selected
    image_deactivated = pyqtSignal(str, str)  # (path, category) when thumbnail deselected

    def __init__(self, title: str, folder: str, category: str, parent=None):
        """Set up the column layout and start the periodic folder-scan timer.

        Args:
            title:    Display title shown above the column (e.g. 'Figures').
            folder:   Absolute path to the input sub-folder to watch.
            category: One of 'Backgrounds', 'Figures', 'Frames'.
        """
        super().__init__(parent)
        self.folder = folder
        self.category = category
        self._thumbnails: dict[str, ImageThumbnail] = {}  # path -> widget

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Column title
        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; color: #bbb; font-size: 11px;")
        layout.addWidget(lbl)

        # Name filter
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter…")
        self._filter.setStyleSheet(
            "background: #333; color: #ccc; border: 1px solid #555; padding: 2px; font-size: 10px;"
        )
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        # Scrollable thumbnail list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background: transparent;")

        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        layout.addWidget(scroll)

        # Refresh timer — checks for new/deleted files every 2 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

        self.refresh()

    def refresh(self):
        """Rescan the folder and add/remove thumbnails to match the current file list.

        Only creates widgets for newly detected files; existing widgets are
        reused.  After reconciling, re-inserts all widgets in newest-first order
        and re-applies the current filter string.
        """
        os.makedirs(self.folder, exist_ok=True)

        try:
            files = [
                os.path.join(self.folder, f)
                for f in os.listdir(self.folder)
                if f.lower().endswith(('.png', '.webp', '.svg', '.jpg', '.jpeg'))
            ]
            files.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            return

        current = set(files)
        existing = set(self._thumbnails)

        # Remove widgets for deleted files
        for path in existing - current:
            thumb = self._thumbnails.pop(path)
            self._list_layout.removeWidget(thumb)
            thumb.deleteLater()

        # Create widgets for new files
        for path in current - existing:
            thumb = ImageThumbnail(path, self.category)
            thumb.clicked.connect(self._on_thumb_clicked)
            self._thumbnails[path] = thumb

        # Re-insert all in sorted (newest-first) order.
        # Use takeAt() for spacer items (which have no .widget()) so they are
        # discarded rather than left to accumulate on every refresh cycle.
        for i in reversed(range(self._list_layout.count())):
            item = self._list_layout.itemAt(i)
            if item and item.widget():
                self._list_layout.removeWidget(item.widget())
            else:
                self._list_layout.takeAt(i)

        for path in files:
            if path in self._thumbnails:
                self._list_layout.addWidget(self._thumbnails[path])
        self._list_layout.addStretch()

        self._apply_filter(self._filter.text())

    def deselect_all(self):
        """Deselect every thumbnail in this column without emitting signals."""
        for thumb in self._thumbnails.values():
            thumb.deselect()

    def deselect_path(self, path: str):
        """Deselect the thumbnail for a specific file path without emitting signals."""
        if path in self._thumbnails:
            self._thumbnails[path].deselect()

    def _apply_filter(self, text: str):
        """Show only thumbnails whose filename contains the filter string (case-insensitive)."""
        text = text.lower()
        for path, thumb in self._thumbnails.items():
            thumb.setVisible(text in os.path.basename(path).lower())

    def _on_thumb_clicked(self, path: str, category: str, selected: bool):
        """Forward thumbnail click events as activation or deactivation signals."""
        if selected:
            self.image_activated.emit(path, category)
        else:
            self.image_deactivated.emit(path, category)


# ---------------------------------------------------------------------------
# Input panel
# ---------------------------------------------------------------------------

class InputPanel(QWidget):
    """The left panel containing three ImageColumns (Backgrounds, Figures, Frames) and a Clear button.

    Aggregates signals from all three columns into a single pair of signals so
    the main window only needs to connect to this panel rather than each column.
    """

    image_activated   = pyqtSignal(str, str)  # (path, category)
    image_deactivated = pyqtSignal(str, str)  # (path, category)
    clear_requested   = pyqtSignal()

    def __init__(self, base_dir: str, parent=None):
        """Create the three input columns pointing at subdirectories of base_dir.

        Args:
            base_dir: The 'Token Generator' folder; subfolders are created if absent.
        """
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Red Clear button aligned to the top-right
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(54)
        clear_btn.setStyleSheet(
            "QPushButton { background: #c0392b; color: white; font-weight: bold;"
            " border: none; padding: 3px 6px; border-radius: 3px; }"
            "QPushButton:hover { background: #e74c3c; }"
        )
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(clear_btn)
        layout.addLayout(btn_row)

        clear_btn.clicked.connect(self.clear_requested)
        clear_btn.clicked.connect(self.deselect_all)

        # Three columns side by side
        cols_widget = QWidget()
        cols_layout = QHBoxLayout(cols_widget)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(2)

        self._columns: list[ImageColumn] = []
        for title, category in [
            ("Backgrounds", "Backgrounds"),
            ("Figures",     "Figures"),
            ("Frames",      "Frames"),
        ]:
            col = ImageColumn(title, os.path.join(base_dir, category), category)
            col.image_activated.connect(self.image_activated)
            col.image_deactivated.connect(self.image_deactivated)
            cols_layout.addWidget(col)
            self._columns.append(col)

        layout.addWidget(cols_widget)

    def deselect_all(self):
        """Deselect every thumbnail across all three columns without emitting signals."""
        for col in self._columns:
            col.deselect_all()

    def deselect_path(self, path: str, category: str):
        """Deselect the thumbnail for a specific file in the matching category column."""
        for col in self._columns:
            if col.category == category:
                col.deselect_path(path)
