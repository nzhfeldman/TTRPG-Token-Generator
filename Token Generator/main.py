"""RPG Token Generator — entry point."""

import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor

from panels.input_panel import InputPanel
from panels.workspace import WorkspaceView, WorkspaceScene, FrameToolbar, WorkspaceTopBar
from panels.output_panel import OutputPanel

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

_DEFAULT_FOLDERS = {
    "Backgrounds": os.path.join(BASE_DIR, "Backgrounds"),
    "Figures":     os.path.join(BASE_DIR, "Figures"),
    "Frames":      os.path.join(BASE_DIR, "Frames"),
    "Tokens":      os.path.join(BASE_DIR, "Tokens"),
}


def _load_config() -> dict:
    """Return folder paths from config.json, falling back to defaults for missing keys."""
    paths = dict(_DEFAULT_FOLDERS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        saved = data.get("folders", {})
        for key in _DEFAULT_FOLDERS:
            if key in saved and saved[key]:
                paths[key] = saved[key]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return paths


def _save_config(paths: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"folders": paths}, f, indent=2)
    except Exception:
        pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RPG Token Generator")
        self.setMinimumSize(1300, 750)
        self.resize(1600, 900)

        self._folder_paths = _load_config()

        self._scene = WorkspaceScene()
        self._input_panel   = InputPanel(BASE_DIR)
        self._workspace     = WorkspaceView(self._scene)
        self._top_bar       = WorkspaceTopBar()
        self._frame_toolbar = FrameToolbar()
        self._output_panel  = OutputPanel(
            self._scene, self._folder_paths["Tokens"]
        )

        self._active_figures: list[str] = []

        # Apply saved folder paths to columns
        for category in ("Backgrounds", "Figures", "Frames"):
            self._input_panel.set_folder(category, self._folder_paths[category])

        self._connect_signals()
        self._init_reference_frame_size()

        # Workspace container: top bar + canvas + frame toolbar
        workspace_container = QWidget()
        wc_layout = QVBoxLayout(workspace_container)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(0)
        wc_layout.addWidget(self._top_bar)
        wc_layout.addWidget(self._workspace)
        wc_layout.addWidget(self._frame_toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._input_panel)
        splitter.addWidget(workspace_container)
        splitter.addWidget(self._output_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 820, 450])
        for i in range(3):
            splitter.setCollapsible(i, False)
        self._input_panel.setMinimumWidth(180)
        workspace_container.setMinimumWidth(200)
        self._output_panel.setMinimumWidth(220)

        self.setCentralWidget(splitter)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self):
        self._input_panel.image_activated.connect(self._on_image_activated)
        self._input_panel.image_deactivated.connect(self._on_image_deactivated)

        self._top_bar.clear_requested.connect(self._scene.clear_all)
        self._top_bar.clear_requested.connect(self._on_clear)
        self._top_bar.clear_requested.connect(self._input_panel.deselect_all)

        self._scene.frame_changed.connect(self._on_frame_changed)
        self._frame_toolbar.frame_params_changed.connect(self._scene.update_frame_params)
        self._scene.item_removed.connect(self._on_item_removed)

        self._output_panel.print_requested.connect(self._handle_print)
        self._output_panel.restore_requested.connect(self._restore_workspace)

        self._top_bar.files_requested.connect(self._show_files_dialog)
        self._top_bar.pdf_requested.connect(self._show_pdf_dialog)

    # ------------------------------------------------------------------
    # Frame / image handlers
    # ------------------------------------------------------------------

    def _on_frame_changed(self, item):
        self._output_panel.preview.update_frame(item)
        if item is None:
            self._frame_toolbar.reset()
            self._frame_toolbar.setEnabled(False)
        else:
            self._frame_toolbar.setEnabled(True)
            self._frame_toolbar.set_params(*item.get_params())
            self._scene.set_reference_frame_size(
                float(item._out_width), float(item._out_height)
            )

    def _on_image_activated(self, path: str, category: str):
        added = self._scene.add_image(path, category)
        if not added:
            self._input_panel.deselect_path(path, category)
            return
        if category == 'Figures':
            if path not in self._active_figures:
                self._active_figures.append(path)
            self._update_last_figure_name()

    def _on_image_deactivated(self, path: str, category: str):
        self._scene.remove_image(path, category)
        if category == 'Figures':
            self._active_figures = [p for p in self._active_figures if p != path]
            self._update_last_figure_name()

    def _on_item_removed(self, path: str, category: str):
        self._input_panel.deselect_path(path, category)
        if category == 'Figures':
            self._active_figures = [p for p in self._active_figures if p != path]
            self._update_last_figure_name()

    def _on_clear(self):
        self._active_figures.clear()

    def _update_last_figure_name(self):
        if self._active_figures:
            self._output_panel.set_last_figure(
                os.path.basename(self._active_figures[-1])
            )

    def _init_reference_frame_size(self):
        frames_col = next(
            (c for c in self._input_panel._columns if c.category == 'Frames'), None
        )
        if frames_col is None:
            return
        try:
            files = sorted(
                [os.path.join(frames_col.folder, f)
                 for f in os.listdir(frames_col.folder)
                 if f.lower().endswith(('.png', '.webp', '.jpg', '.jpeg', '.svg'))],
                key=os.path.getmtime, reverse=True,
            )
            if not files:
                return
            path = files[0]
            if path.lower().endswith('.svg'):
                from panels.utils import load_pixmap
                px = load_pixmap(path, max_size=4096)
                if not px.isNull():
                    s = min(400.0 / px.width(), 400.0 / px.height())
                    self._scene.set_reference_frame_size(px.width() * s, px.height() * s)
            else:
                from PIL import Image
                img = Image.open(path)
                w, h = img.size
                s = min(400.0 / w, 400.0 / h)
                self._scene.set_reference_frame_size(w * s, h * s)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------

    def _handle_print(self):
        """Show print options dialog, render at the frame's output size, and save."""
        from panels.dialogs import PrintOptionsDialog

        w, h = self._scene.get_output_size()
        last_name = getattr(self._output_panel, '_last_figure_name', 'token')
        dlg = PrintOptionsDialog(
            default_name=last_name,
            tokens_dir=self._folder_paths["Tokens"],
            output_size=(w, h),
            initial_settings=self._output_panel.get_print_settings(),
            parent=self,
        )
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        settings = dlg.get_settings()
        settings["width"]  = w
        settings["height"] = h
        image = self._output_panel.preview.render_token(w, h)
        if image is None:
            return

        state = self._scene.get_workspace_state()
        self._output_panel.save_token(image, state, settings)

    # ------------------------------------------------------------------
    # Restore workspace
    # ------------------------------------------------------------------

    def _restore_workspace(self, state: list, print_settings: dict):
        self._input_panel.deselect_all()
        self._active_figures.clear()
        self._scene.restore_workspace_state(state)

        active_paths = self._scene.get_active_paths()
        for col in self._input_panel._columns:
            for path, thumb in col._thumbnails.items():
                if path in active_paths:
                    thumb.selected = True

        for s in sorted(state, key=lambda x: x.get('layer', 0)):
            if s.get('category') == 'Figures' and s['path'] in active_paths:
                self._active_figures.append(s['path'])
        self._update_last_figure_name()

        # Restore print settings into the output panel
        if print_settings:
            self._output_panel._print_settings = dict(print_settings)

    # ------------------------------------------------------------------
    # Files dialog
    # ------------------------------------------------------------------

    def _show_files_dialog(self):
        from panels.dialogs import FilesDialog
        dlg = FilesDialog(dict(self._folder_paths), parent=self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        new_paths = dlg.get_paths()
        changed = {k for k in new_paths if new_paths[k] != self._folder_paths.get(k)}
        self._folder_paths.update(new_paths)
        _save_config(self._folder_paths)

        # Apply changes live
        for category in ("Backgrounds", "Figures", "Frames"):
            if category in changed:
                self._input_panel.set_folder(category, new_paths[category])
        if "Tokens" in changed:
            self._output_panel.set_tokens_dir(new_paths["Tokens"])

    # ------------------------------------------------------------------
    # PDF dialog
    # ------------------------------------------------------------------

    def _show_pdf_dialog(self):
        from panels.dialogs import PDFExtractDialog
        dlg = PDFExtractDialog(dict(self._folder_paths), parent=self)
        dlg.exec()


# ------------------------------------------------------------------
# Dark theme
# ------------------------------------------------------------------

def _apply_dark_theme(app: QApplication):
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window,          QColor(30, 30, 30))
    p.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Base,            QColor(22, 22, 22))
    p.setColor(QPalette.ColorRole.AlternateBase,   QColor(35, 35, 35))
    p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(40, 40, 40))
    p.setColor(QPalette.ColorRole.ToolTipText,     QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.Button,          QColor(48, 48, 48))
    p.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
    p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 80, 80))
    p.setColor(QPalette.ColorRole.Link,            QColor(80, 140, 220))
    p.setColor(QPalette.ColorRole.Highlight,       QColor(55, 115, 195))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(p)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("RPG Token Generator")
    _apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
