import os
import shutil
import subprocess
import sys
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel,
    QPushButton, QLineEdit, QMenu, QMessageBox, QFileDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread, QObject
from PyQt6.QtGui import QPainter, QPen, QBrush, QColor, QPixmap, QFont
from panels.utils import load_pixmap, IconButton

THUMBNAIL_SIZE = 80
GLOW_HOVER    = QColor(100, 180, 255)
GLOW_SELECTED = QColor(50, 110, 210)

SUPPORTED_EXTS = ('.png', '.webp', '.svg', '.jpg', '.jpeg')


# ---------------------------------------------------------------------------
# Background-removal worker
# ---------------------------------------------------------------------------

class BgRemoveWorker(QObject):
    finished = pyqtSignal(str)
    failed   = pyqtSignal(str)

    _SCRIPT = (
        "from rembg import remove; from PIL import Image; "
        "img = Image.open({src!r}); "
        "result = remove(img); "
        "result.save({dst!r}, 'PNG')"
    )

    def __init__(self, input_path: str):
        super().__init__()
        self.input_path = input_path

    def run(self):
        try:
            stem, _ = os.path.splitext(self.input_path)
            output_path = stem + "_nobg.png"
            script = self._SCRIPT.format(src=self.input_path, dst=output_path)
            result = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                self.finished.emit(output_path)
            else:
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
    clicked = pyqtSignal(str, str, bool)

    def __init__(self, path: str, category: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.category = category
        self._selected  = False
        self._hovered   = False
        self._processing = False

        self.setFixedSize(THUMBNAIL_SIZE + 12, THUMBNAIL_SIZE + 12)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(path))

        raw = load_pixmap(path, max_size=THUMBNAIL_SIZE * 2)
        if raw.isNull():
            self._pixmap = None
        else:
            self._pixmap = raw.scaled(
                THUMBNAIL_SIZE, THUMBNAIL_SIZE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        self._thread: QThread | None = None
        self._worker: BgRemoveWorker | None = None

    def deselect(self):
        self._selected = False
        self.update()

    @property
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool):
        self._selected = value
        self.update()

    def _start_bg_removal(self):
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
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_finished(self, output_path: str):
        self._processing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(self.path))
        self.update()

    def _on_failed(self, message: str):
        self._processing = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(os.path.basename(self.path))
        self.update()
        QMessageBox.warning(None, "Background Removal Failed", message)

    def paintEvent(self, event):
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
            painter.setBrush(QBrush(QColor(0, 0, 0, 160)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(2, 2, self.width() - 4, self.height() - 4, 4, 4)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.setFont(QFont("Arial", 7, QFont.Weight.Bold))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Removing\nBG…")

        painter.end()

    def mousePressEvent(self, event):
        if self._processing: return
        if event.button() == Qt.MouseButton.LeftButton:
            self._selected = not self._selected
            self.clicked.emit(self.path, self.category, self._selected)
            self.update()

    def contextMenuEvent(self, event):
        menu = QMenu()
        remove_act = menu.addAction("Remove Background")
        remove_act.setEnabled(not self._processing)
        action = menu.exec(event.globalPos())
        if action == remove_act:
            self._start_bg_removal()

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()


# ---------------------------------------------------------------------------
# Column widget
# ---------------------------------------------------------------------------

class ImageColumn(QWidget):
    """Scrollable, filterable column of thumbnails for one input folder.

    A 'Catch' button at the top lets users copy files from anywhere on disk
    into this folder. set_folder() lets the Files dialog redirect the column.
    """

    image_activated   = pyqtSignal(str, str)
    image_deactivated = pyqtSignal(str, str)

    def __init__(self, title: str, folder: str, category: str, parent=None):
        super().__init__(parent)
        self.folder   = folder
        self.category = category
        self._thumbnails: dict[str, ImageThumbnail] = {}
        self._sorted_paths: list[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Column title
        lbl = QLabel(title)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-weight: bold; color: #bbb; font-size: 11px;")
        layout.addWidget(lbl)

        # Catch button
        catch_row = QHBoxLayout()
        catch_row.setContentsMargins(0, 0, 0, 0)
        self._catch_btn = IconButton(
            'catch', QColor(42, 84, 147),
            f"Import image files into {title} folder"
        )
        self._catch_btn.clicked.connect(self._catch_files)
        catch_row.addStretch()
        catch_row.addWidget(self._catch_btn)
        catch_row.addStretch()
        layout.addLayout(catch_row)

        # Name filter
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter…")
        self._filter.setStyleSheet(
            "background: #333; color: #ccc; border: 1px solid #555;"
            " padding: 2px; font-size: 10px;"
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

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)

        self.refresh()

    # ------------------------------------------------------------------

    def set_folder(self, new_folder: str):
        """Redirect this column to a different folder path."""
        self.folder = new_folder
        # Clear existing thumbnails so next refresh builds from scratch
        for thumb in list(self._thumbnails.values()):
            self._list_layout.removeWidget(thumb)
            thumb.deleteLater()
        self._thumbnails.clear()
        self._sorted_paths.clear()
        self.refresh()

    def _catch_files(self):
        """Open a file browser and copy selected images into this column's folder."""
        files, _ = QFileDialog.getOpenFileNames(
            self, f"Import into {self.category}",
            "",
            "Images (*.png *.webp *.jpg *.jpeg *.svg *.bmp *.tiff *.tif)"
        )
        if not files:
            return

        os.makedirs(self.folder, exist_ok=True)
        copied, skipped = 0, 0
        for src in files:
            fname = os.path.basename(src)
            dst = os.path.join(self.folder, fname)
            # Avoid silently overwriting existing files
            base, ext = os.path.splitext(dst)
            n = 1
            while os.path.exists(dst):
                dst = f"{base}_{n}{ext}"
                n += 1
            try:
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                skipped += 1

        msg = f"Copied {copied} file{'s' if copied != 1 else ''} into {self.category}."
        if skipped:
            msg += f"\n{skipped} file{'s' if skipped != 1 else ''} could not be copied."
        QMessageBox.information(self, "Import Complete", msg)

    def refresh(self):
        os.makedirs(self.folder, exist_ok=True)
        try:
            files = [
                os.path.join(self.folder, f)
                for f in os.listdir(self.folder)
                if f.lower().endswith(SUPPORTED_EXTS)
            ]
            files.sort(key=os.path.getmtime, reverse=True)
        except OSError:
            return

        current  = set(files)
        existing = set(self._thumbnails)

        for path in existing - current:
            thumb = self._thumbnails.pop(path)
            self._list_layout.removeWidget(thumb)
            thumb.deleteLater()

        for path in current - existing:
            thumb = ImageThumbnail(path, self.category)
            thumb.clicked.connect(self._on_thumb_clicked)
            self._thumbnails[path] = thumb

        new_order = [p for p in files if p in self._thumbnails]
        if new_order != self._sorted_paths:
            self._sorted_paths = new_order
            for i in reversed(range(self._list_layout.count())):
                item = self._list_layout.itemAt(i)
                if item and item.widget():
                    self._list_layout.removeWidget(item.widget())
                else:
                    self._list_layout.takeAt(i)
            for path in new_order:
                self._list_layout.addWidget(self._thumbnails[path])
            self._list_layout.addStretch()
            self._apply_filter(self._filter.text())

    def deselect_all(self):
        for thumb in self._thumbnails.values():
            thumb.deselect()

    def deselect_path(self, path: str):
        if path in self._thumbnails:
            self._thumbnails[path].deselect()

    def _apply_filter(self, text: str):
        text = text.lower()
        for path, thumb in self._thumbnails.items():
            thumb.setVisible(text in os.path.basename(path).lower())

    def _on_thumb_clicked(self, path: str, category: str, selected: bool):
        if selected:
            self.image_activated.emit(path, category)
        else:
            self.image_deactivated.emit(path, category)


# ---------------------------------------------------------------------------
# Input panel
# ---------------------------------------------------------------------------

class InputPanel(QWidget):
    """Left panel: three ImageColumns (Frames, Backgrounds, Figures) + Clear button."""

    image_activated   = pyqtSignal(str, str)
    image_deactivated = pyqtSignal(str, str)

    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # Three columns
        cols_widget = QWidget()
        cols_layout = QHBoxLayout(cols_widget)
        cols_layout.setContentsMargins(0, 0, 0, 0)
        cols_layout.setSpacing(2)

        self._columns: list[ImageColumn] = []
        for title, category in [
            ("Frames",      "Frames"),
            ("Backgrounds", "Backgrounds"),
            ("Figures",     "Figures"),
        ]:
            col = ImageColumn(title, os.path.join(base_dir, category), category)
            col.image_activated.connect(self.image_activated)
            col.image_deactivated.connect(self.image_deactivated)
            cols_layout.addWidget(col)
            self._columns.append(col)

        layout.addWidget(cols_widget)

    def deselect_all(self):
        for col in self._columns:
            col.deselect_all()

    def deselect_path(self, path: str, category: str):
        for col in self._columns:
            if col.category == category:
                col.deselect_path(path)

    def set_folder(self, category: str, path: str):
        """Redirect the column for the given category to a new folder path."""
        for col in self._columns:
            if col.category == category:
                col.set_folder(path)
                break
