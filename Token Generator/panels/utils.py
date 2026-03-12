"""Shared image-loading utilities used by both the input panel and the workspace.

SVG files cannot be loaded directly by QPixmap, so they are rasterized via
QSvgRenderer at a caller-specified maximum resolution.  All other formats
(PNG, WebP) are passed straight through to QPixmap.
"""

from PyQt6.QtGui import QPixmap, QPainter
from PyQt6.QtCore import Qt


def load_pixmap(path: str, max_size: int = 1024) -> QPixmap:
    """Load any supported image file and return it as a QPixmap.

    Raster files (PNG, WebP) are returned at their native pixel dimensions.
    SVG files are rasterized so their longest side is at most max_size pixels,
    with the natural aspect ratio preserved.

    Args:
        path:     Absolute path to the image file.
        max_size: Maximum dimension (width or height) for SVG rasterisation.
                  Has no effect on raster images.

    Returns:
        A valid QPixmap, or a null QPixmap if the file could not be loaded.
    """
    if path.lower().endswith(".svg"):
        return _svg_to_pixmap(path, max_size)
    return QPixmap(path)


def _svg_to_pixmap(path: str, max_size: int) -> QPixmap:
    """Rasterize an SVG file to a QPixmap using Qt's built-in SVG renderer.

    The image is rendered at the SVG's natural aspect ratio, scaled so that
    the longer dimension equals max_size.  The result has a transparent
    background, which is important for frames and figure cut-outs.

    Args:
        path:     Absolute path to the .svg file.
        max_size: The maximum pixel dimension of the output pixmap.

    Returns:
        A valid QPixmap on success, or a null QPixmap if the SVG is invalid.
    """
    from PyQt6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(path)
    if not renderer.isValid():
        return QPixmap()

    natural = renderer.defaultSize()
    if natural.isEmpty():
        w = h = max_size
    elif natural.width() >= natural.height():
        w = max_size
        h = max(1, round(max_size * natural.height() / natural.width()))
    else:
        h = max_size
        w = max(1, round(max_size * natural.width() / natural.height()))

    pixmap = QPixmap(w, h)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
