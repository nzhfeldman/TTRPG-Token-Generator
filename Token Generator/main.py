"""RPG Token Generator — entry point.

Run with:
    python main.py

Requires: PyQt6, Pillow, numpy  (pip install -r requirements.txt)
"""

import sys
import os

# Ensure the 'panels' package is importable when running from any working directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QMainWindow, QSplitter
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPalette, QColor

from panels.input_panel import InputPanel
from panels.workspace import WorkspaceView, WorkspaceScene
from panels.output_panel import OutputPanel

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
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

        self._input_panel  = InputPanel(BASE_DIR)
        self._workspace    = WorkspaceView(self._scene)
        self._output_panel = OutputPanel(self._scene, TOKENS_DIR)

        self._connect_signals()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._input_panel)
        splitter.addWidget(self._workspace)
        splitter.addWidget(self._output_panel)
        # Centre panel stretches; side panels start at a fixed comfortable width
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([330, 820, 450])

        self.setCentralWidget(splitter)

    def _connect_signals(self):
        """Wire all cross-panel signals in one place for easy auditing."""
        # Thumbnail selection → workspace
        self._input_panel.image_activated.connect(self._on_image_activated)
        self._input_panel.image_deactivated.connect(self._on_image_deactivated)

        # Clear button → scene + input panel (input panel deselects itself via its own slot)
        self._input_panel.clear_requested.connect(self._scene.clear_all)

        # Frame change → preview
        self._scene.frame_changed.connect(self._output_panel.preview.update_frame)

        # Item removed via right-click → deselect the corresponding thumbnail
        self._scene.item_removed.connect(self._on_item_removed)

        # Print button → capture + save
        self._output_panel.print_requested.connect(self._handle_print)

        # Session entry clicked → restore workspace
        self._output_panel.restore_requested.connect(self._restore_workspace)

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_image_activated(self, path: str, category: str):
        """Add the image to the scene; deselect its thumbnail if the limit was reached.

        Also updates the output panel's default print name whenever a figure is
        activated, so 'Print' is pre-filled with a sensible suggestion.
        """
        added = self._scene.add_image(path, category)
        if not added:
            # Limit was hit — undo the visual selection in the input panel
            self._input_panel.deselect_path(path, category)
            return
        if category == 'Figures':
            self._output_panel.set_last_figure(os.path.basename(path))

    def _on_image_deactivated(self, path: str, category: str):
        """Remove the image from the scene when the user deselects its thumbnail."""
        self._scene.remove_image(path, category)

    def _on_item_removed(self, path: str, category: str):
        """Deselect the thumbnail when an item is removed via the right-click context menu."""
        self._input_panel.deselect_path(path, category)

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
        self._scene.restore_workspace_state(state)

        # Re-select the thumbnails for all restored items
        active_paths = self._scene.get_active_paths()
        for col in self._input_panel._columns:
            for path, thumb in col._thumbnails.items():
                if path in active_paths:
                    thumb.selected = True


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
