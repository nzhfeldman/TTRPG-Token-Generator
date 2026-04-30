"""RPG Token Generator — entry point.

Run with:
    python main.py

Requires: PyQt6, Pillow, numpy  (pip install -r requirements.txt)
"""

import sys
import os

# Ensure the 'panels' package is importable when running from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMainWindow, QSplitter, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor

from panels.input_panel import InputPanel
from panels.workspace import WorkspaceView, WorkspaceScene, FrameToolbar
from panels.output_panel import OutputPanel

# When frozen by PyInstaller (--onefile) sys.executable is the .exe path;
# its directory is where the user placed the asset folders.
# When running from source, fall back to the script's own directory.
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

TOKENS_DIR = os.path.join(BASE_DIR, "Tokens")


class MainWindow(QMainWindow):
    """Top-level window that owns the three panels and wires their signals together.

    Layout (left to right inside a QSplitter):
      - InputPanel     — file columns + Clear button
      - WorkspaceView  — interactive canvas
      - OutputPanel    — preview + Print + session memory

    Signal flow:
      InputPanel  →  scene.add_image / scene.remove_image
      scene       →  output_panel.preview.update_frame  (frame changed)
      scene       →  input_panel.deselect_path          (item removed via right-click)
      OutputPanel →  _handle_print                      (Print button)
      OutputPanel →  _restore_workspace                 (session entry clicked)
    """

    def __init__(self):
        """Construct all panels, connect signals, and set the initial splitter sizes."""
        super().__init__()
        self.setWindowTitle("RPG Token Generator")
        self.setMinimumSize(1300, 750)
        self.resize(1600, 900)

        # Shared scene — single source of truth for workspace items
        self._scene = WorkspaceScene()

        self._input_panel   = InputPanel(BASE_DIR)
        self._workspace     = WorkspaceView(self._scene)
        self._frame_toolbar = FrameToolbar()
        self._output_panel  = OutputPanel(self._scene, TOKENS_DIR)

        # Ordered list of active figure paths (most recently activated is last)
        self._active_figures: list[str] = []

        self._connect_signals()
        self._init_reference_frame_size()

        # Wrap the canvas and frame toolbar together so they behave as one splitter panel
        workspace_container = QWidget()
        wc_layout = QVBoxLayout(workspace_container)
        wc_layout.setContentsMargins(0, 0, 0, 0)
        wc_layout.setSpacing(0)
        wc_layout.addWidget(self._workspace)
        wc_layout.addWidget(self._frame_toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._input_panel)
        splitter.addWidget(workspace_container)
        splitter.addWidget(self._output_panel)
        # Centre panel stretches; side panels start at a fixed comfortable width
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 820, 450])
        # Prevent any panel from being dragged to zero width
        for i in range(3):
            splitter.setCollapsible(i, False)
        self._input_panel.setMinimumWidth(180)
        workspace_container.setMinimumWidth(200)
        self._output_panel.setMinimumWidth(220)

        self.setCentralWidget(splitter)

    def _connect_signals(self):
        """Wire all cross-panel signals in one place for easy auditing."""
        # Thumbnail selection → workspace
        self._input_panel.image_activated.connect(self._on_image_activated)
        self._input_panel.image_deactivated.connect(self._on_image_deactivated)

        # Clear button → scene + input panel (input panel deselects itself via its own slot)
        self._input_panel.clear_requested.connect(self._scene.clear_all)

        # Frame change → preview + toolbar state
        self._scene.frame_changed.connect(self._on_frame_changed)

        # Frame toolbar sliders → scene frame params
        self._frame_toolbar.frame_params_changed.connect(self._scene.update_frame_params)

        # Item removed via right-click → deselect the corresponding thumbnail
        self._scene.item_removed.connect(self._on_item_removed)

        # Clear → reset active-figures tracking
        self._input_panel.clear_requested.connect(self._on_clear)

        # Print button → capture + save
        self._output_panel.print_requested.connect(self._handle_print)

        # Session entry clicked → restore workspace
        self._output_panel.restore_requested.connect(self._restore_workspace)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_frame_changed(self, item):
        """Update the preview and the frame toolbar when the active frame changes."""
        self._output_panel.preview.update_frame(item)
        if item is None:
            self._frame_toolbar.reset()
            self._frame_toolbar.setEnabled(False)
        else:
            self._frame_toolbar.setEnabled(True)
            self._frame_toolbar.set_params(*item.get_params())
            # Keep the reference size current so newly placed items scale correctly
            self._scene.set_reference_frame_size(float(item._pw), float(item._ph))

    def _on_image_activated(self, path: str, category: str):
        """Add the image to the scene; deselect its thumbnail if the limit was reached."""
        added = self._scene.add_image(path, category)
        if not added:
            self._input_panel.deselect_path(path, category)
            return
        if category == 'Figures':
            if path not in self._active_figures:
                self._active_figures.append(path)
            self._update_last_figure_name()

    def _on_image_deactivated(self, path: str, category: str):
        """Remove the image from the scene when the user deselects its thumbnail."""
        self._scene.remove_image(path, category)
        if category == 'Figures':
            self._active_figures = [p for p in self._active_figures if p != path]
            self._update_last_figure_name()

    def _on_item_removed(self, path: str, category: str):
        """Deselect the thumbnail when an item is removed via the right-click context menu."""
        self._input_panel.deselect_path(path, category)
        if category == 'Figures':
            self._active_figures = [p for p in self._active_figures if p != path]
            self._update_last_figure_name()

    def _on_clear(self):
        """Reset active-figure tracking when the workspace is cleared."""
        self._active_figures.clear()

    def _update_last_figure_name(self):
        """Set the output panel's default print name to the most recently activated figure."""
        if self._active_figures:
            self._output_panel.set_last_figure(os.path.basename(self._active_figures[-1]))

    def _init_reference_frame_size(self):
        """Read the topmost frame file's dimensions and store them as the auto-scale fallback."""
        frames_col = next((c for c in self._input_panel._columns if c.category == 'Frames'), None)
        if frames_col is None:
            return
        try:
            files = sorted(
                [os.path.join(frames_col.folder, f) for f in os.listdir(frames_col.folder)
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
                    self._scene.set_reference_frame_size(float(px.width()), float(px.height()))
            else:
                from PIL import Image
                img = Image.open(path)
                w, h = img.size
                if max(w, h) > 1024:
                    scale = 1024 / max(w, h)
                    w, h = int(w * scale), int(h * scale)
                self._scene.set_reference_frame_size(float(w), float(h))
        except Exception:
            pass

    def _handle_print(self):
        """Render the current token and hand it to the output panel to save and archive."""
        image = self._output_panel.preview.render_token()
        if image is not None:
            state = self._scene.get_workspace_state()
            self._output_panel.save_token(image, state)

    def _restore_workspace(self, state: list):
        """Clear the current workspace and rebuild it from a session memory snapshot.

        Also re-selects the thumbnails that correspond to restored items so the
        input panel stays in sync with what is visible on the canvas.
        """
        self._input_panel.deselect_all()
        self._active_figures.clear()
        self._scene.restore_workspace_state(state)

        # Re-select the thumbnails for all restored items
        active_paths = self._scene.get_active_paths()
        for col in self._input_panel._columns:
            for path, thumb in col._thumbnails.items():
                if path in active_paths:
                    thumb.selected = True

        # Rebuild active figures from the restored state (layer order as proxy for activation order)
        for s in sorted(state, key=lambda x: x.get('layer', 0)):
            if s.get('category') == 'Figures' and s['path'] in active_paths:
                self._active_figures.append(s['path'])
        self._update_last_figure_name()


# ------------------------------------------------------------------
# Dark theme
# ------------------------------------------------------------------

def _apply_dark_theme(app: QApplication):
    """Apply a dark QPalette so native widgets (scrollbars, dialogs) match the dark UI."""
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
