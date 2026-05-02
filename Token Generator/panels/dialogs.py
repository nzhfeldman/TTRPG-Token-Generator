"""Modal dialogs: print options, folder paths, and PDF image extraction."""

import os
import shutil
import base64

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QSpinBox, QFileDialog, QScrollArea, QWidget,
    QMessageBox, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QPixmap, QImage


# ---------------------------------------------------------------------------
# PrintOptionsDialog
# ---------------------------------------------------------------------------

class PrintOptionsDialog(QDialog):
    """Print-options dialog: token name, file format, and destination folder.

    Output pixel dimensions are set in the Frame toolbar (Width / Height) and
    displayed here as read-only information.  Print settings are persisted in
    the caller as a plain dict and passed back in `initial_settings`.
    """

    FORMATS = ["WebP", "PNG", "JPEG", "SVG"]

    def __init__(self, default_name: str, tokens_dir: str,
                 output_size: 'tuple[int, int]',
                 initial_settings: dict | None = None,
                 parent=None):
        """
        Args:
            default_name:     Pre-filled filename stem (no extension).
            tokens_dir:       Default Tokens folder path.
            output_size:      (width, height) in pixels from the frame toolbar.
            initial_settings: Dict from a previous print; keys: format, folder.
        """
        super().__init__(parent)
        self.setWindowTitle("Print Token")
        self.setMinimumWidth(420)
        s = initial_settings or {}

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        # Token name
        self._name = QLineEdit(default_name)
        form.addRow("Name:", self._name)

        # Format
        self._fmt = QComboBox()
        self._fmt.addItems(self.FORMATS)
        saved_fmt = s.get("format", "WebP")
        idx = next((i for i, f in enumerate(self.FORMATS)
                    if f.lower() == saved_fmt.lower()), 0)
        self._fmt.setCurrentIndex(idx)
        form.addRow("Format:", self._fmt)

        # Destination folder
        folder_row = QHBoxLayout()
        self._folder = QLineEdit(s.get("folder", tokens_dir))
        self._folder.setMinimumWidth(240)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(72)
        browse_btn.clicked.connect(self._browse_folder)
        folder_row.addWidget(self._folder)
        folder_row.addWidget(browse_btn)
        form.addRow("Folder:", folder_row)

        # Output size — read-only, driven by Frame toolbar Width/Height
        w, h = output_size
        size_lbl = QLabel(f"{w} × {h} px  (set via Frame toolbar)")
        size_lbl.setStyleSheet("color: #aaa; font-size: 10px;")
        form.addRow("Output size:", size_lbl)

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------

    def _browse_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Destination Folder", self._folder.text()
        )
        if path:
            self._folder.setText(path)

    def get_settings(self) -> dict:
        return {
            "name":   self._name.text().strip() or "token",
            "format": self._fmt.currentText(),
            "folder": self._folder.text().strip(),
        }


# ---------------------------------------------------------------------------
# FilesDialog
# ---------------------------------------------------------------------------

class FilesDialog(QDialog):
    """Dialog for viewing and editing the four asset folder paths.

    Changes take effect immediately upon OK; the dialog returns the updated
    paths dict so the caller can persist them and update the live panels.
    """

    KEYS = ["Backgrounds", "Figures", "Frames", "Tokens"]

    def __init__(self, paths: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Folder Paths")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        info = QLabel(
            "These folders are used as input/output for the Token Generator.\n"
            "Changes apply for the rest of this session and are saved between sessions."
        )
        info.setStyleSheet("color: #aaa; font-size: 10px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setSpacing(8)

        self._edits: dict[str, QLineEdit] = {}
        for key in self.KEYS:
            row = QHBoxLayout()
            edit = QLineEdit(paths.get(key, ""))
            edit.setMinimumWidth(300)
            browse = QPushButton("Browse…")
            browse.setFixedWidth(72)
            browse.clicked.connect(lambda _, e=edit: self._browse(e))
            row.addWidget(edit)
            row.addWidget(browse)
            form.addRow(f"{key}:", row)
            self._edits[key] = edit

        layout.addLayout(form)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse(self, edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(
            self, "Select Folder", edit.text()
        )
        if path:
            edit.setText(path)

    def get_paths(self) -> dict:
        return {key: self._edits[key].text().strip() for key in self.KEYS}


# ---------------------------------------------------------------------------
# PDFExtractDialog
# ---------------------------------------------------------------------------

class PDFExtractDialog(QDialog):
    """Extract raster images from a PDF and send them to an asset folder.

    Workflow:
      1. User picks a PDF file and optionally specifies a page range.
      2. Click Extract — images are read with pypdf.
      3. Extracted thumbnails appear in a scrollable grid.
      4. User clicks a destination button (Backgrounds / Figures / Frames / Tokens)
         to copy all extracted images into that folder.
    """

    def __init__(self, folder_paths: dict, parent=None):
        """
        Args:
            folder_paths: dict with keys Backgrounds, Figures, Frames, Tokens
                          pointing to the current folder paths.
        """
        super().__init__(parent)
        self.setWindowTitle("Extract Images from PDF")
        self.setMinimumSize(560, 480)
        self._folder_paths = folder_paths
        self._extracted: list[tuple[str, str]] = []  # (temp_path, filename)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # PDF selection row
        top = QHBoxLayout()
        self._pdf_path = QLineEdit()
        self._pdf_path.setPlaceholderText("Select a PDF file…")
        pick_btn = QPushButton("Browse…")
        pick_btn.setFixedWidth(72)
        pick_btn.clicked.connect(self._pick_pdf)
        top.addWidget(self._pdf_path)
        top.addWidget(pick_btn)
        layout.addLayout(top)

        # Page range
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Page range (leave blank for all):"))
        self._page_from = QSpinBox()
        self._page_from.setRange(1, 9999)
        self._page_from.setValue(1)
        self._page_from.setFixedWidth(64)
        self._page_to = QSpinBox()
        self._page_to.setRange(1, 9999)
        self._page_to.setValue(9999)
        self._page_to.setFixedWidth(64)
        range_row.addWidget(QLabel("From:"))
        range_row.addWidget(self._page_from)
        range_row.addWidget(QLabel("To:"))
        range_row.addWidget(self._page_to)
        range_row.addStretch()
        layout.addLayout(range_row)

        # Extract button + status
        extract_row = QHBoxLayout()
        self._extract_btn = QPushButton("Extract Images")
        self._extract_btn.setFixedWidth(130)
        self._extract_btn.clicked.connect(self._extract)
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet("color: #aaa; font-size: 10px;")
        extract_row.addWidget(self._extract_btn)
        extract_row.addWidget(self._status_lbl)
        extract_row.addStretch()
        layout.addLayout(extract_row)

        # Thumbnail grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: 1px solid #3a3a3a; background: #1c1c1c;")
        self._grid_widget = QWidget()
        from PyQt6.QtWidgets import QGridLayout
        self._grid = QGridLayout(self._grid_widget)
        self._grid.setSpacing(6)
        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll, 1)

        # Destination buttons
        dest_lbl = QLabel("Send all extracted images to:")
        dest_lbl.setStyleSheet("color: #bbb; font-size: 10px; margin-top: 4px;")
        layout.addWidget(dest_lbl)

        dest_row = QHBoxLayout()
        for key in ["Backgrounds", "Figures", "Frames", "Tokens"]:
            btn = QPushButton(key)
            btn.clicked.connect(lambda _, k=key: self._send_to(k))
            dest_row.addWidget(btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        dest_row.addStretch()
        dest_row.addWidget(close_btn)
        layout.addLayout(dest_row)

    # ------------------------------------------------------------------

    def _pick_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select PDF", "", "PDF Files (*.pdf)"
        )
        if path:
            self._pdf_path.setText(path)

    def _extract(self):
        pdf_path = self._pdf_path.text().strip()
        if not pdf_path or not os.path.isfile(pdf_path):
            QMessageBox.warning(self, "No PDF", "Please select a valid PDF file first.")
            return

        try:
            from pypdf import PdfReader
        except ImportError:
            QMessageBox.critical(
                self, "Missing Dependency",
                "pypdf is not installed.\n\nRun:  pip install pypdf"
            )
            return

        try:
            reader = PdfReader(pdf_path)
        except Exception as e:
            QMessageBox.critical(self, "PDF Error", f"Could not open PDF:\n{e}")
            return

        page_from = self._page_from.value() - 1          # 0-indexed
        page_to   = min(self._page_to.value(), len(reader.pages))  # inclusive end

        # Clear previous results
        for i in reversed(range(self._grid.count())):
            item = self._grid.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()
        self._extracted.clear()

        import tempfile
        self._tmp_dir = tempfile.mkdtemp(prefix="token_gen_pdf_")

        count = 0
        for page_idx in range(page_from, page_to):
            try:
                page = reader.pages[page_idx]
            except IndexError:
                break

            if not hasattr(page, "images"):
                continue

            for img_obj in page.images:
                try:
                    ext = os.path.splitext(img_obj.name)[1].lower()
                    if ext not in ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.tif'):
                        ext = '.png'
                    fname = f"page{page_idx + 1}_{img_obj.name or f'img{count}'}{ext}"
                    # Sanitize filename
                    fname = "".join(c for c in fname if c.isalnum() or c in ('_', '-', '.'))
                    out_path = os.path.join(self._tmp_dir, fname)
                    with open(out_path, 'wb') as f:
                        f.write(img_obj.data)

                    self._extracted.append((out_path, fname))

                    # Thumbnail
                    px = QPixmap(out_path)
                    if not px.isNull():
                        px = px.scaled(80, 80,
                                       Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation)
                        lbl = QLabel()
                        lbl.setPixmap(px)
                        lbl.setFixedSize(88, 88)
                        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        lbl.setStyleSheet("background: #2a2a2a; border: 1px solid #444;")
                        lbl.setToolTip(fname)
                        row, col = divmod(count, 5)
                        self._grid.addWidget(lbl, row, col)

                    count += 1
                except Exception:
                    continue

        self._status_lbl.setText(
            f"{count} image{'s' if count != 1 else ''} extracted from "
            f"pages {page_from + 1}–{page_to}."
        )

    def _send_to(self, folder_key: str):
        if not self._extracted:
            QMessageBox.information(self, "Nothing to Send",
                                    "Extract images from a PDF first.")
            return

        dest = self._folder_paths.get(folder_key, "")
        if not dest:
            QMessageBox.warning(self, "No Folder", f"No path set for {folder_key}.")
            return

        os.makedirs(dest, exist_ok=True)
        copied = 0
        for src, fname in self._extracted:
            try:
                dst = os.path.join(dest, fname)
                # Avoid overwriting: add suffix if needed
                base, ext = os.path.splitext(dst)
                n = 1
                while os.path.exists(dst):
                    dst = f"{base}_{n}{ext}"
                    n += 1
                shutil.copy2(src, dst)
                copied += 1
            except Exception:
                continue

        QMessageBox.information(
            self, "Done",
            f"Copied {copied} image{'s' if copied != 1 else ''} to:\n{dest}"
        )
