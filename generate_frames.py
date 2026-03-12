"""Generate 18 sample token frame PNGs (6 colours × 3 shapes).

Output goes directly to Token Generator/Frames/ so they appear in the app
immediately.  Run once from the Claude-Token Generator folder:

    python generate_frames.py
"""

import os
import numpy as np
from PIL import Image, ImageFilter

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIZE   = 512          # image dimensions (square)
CX = CY = SIZE // 2
BORDER = 52           # visual ring width in pixels

COLOURS = {
    "white": (240, 240, 240, 255),
    "black": ( 18,  18,  18, 255),
    "beige": (205, 175, 130, 255),
    "red":   (185,  38,  38, 255),
    "blue":  ( 35,  88, 178, 255),
    "green": ( 35, 148,  68, 255),
}

OUT_DIR = os.path.join(os.path.dirname(__file__), "Token Generator", "Frames")


# ---------------------------------------------------------------------------
# Alpha helpers
# ---------------------------------------------------------------------------

def _soft_alpha(mask: np.ndarray, blur: float = 1.2) -> np.ndarray:
    """Convert a boolean pixel mask to a soft uint8 alpha channel.

    Applies a small Gaussian blur so edges are anti-aliased rather than
    jagged 1-pixel steps.
    """
    raw = (mask.astype(np.float32) * 255).astype(np.uint8)
    blurred = np.array(Image.fromarray(raw, "L").filter(ImageFilter.GaussianBlur(blur)))
    return blurred


def _assemble(alpha: np.ndarray, colour: tuple) -> Image.Image:
    """Build an RGBA Image from a float/uint8 alpha array and an RGBA colour tuple.

    Only pixels with non-zero alpha receive the frame colour; all others remain
    fully transparent so the file has clean edges for the flood-fill masker.
    """
    img = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    mask = alpha > 0
    img[mask, 0] = colour[0]
    img[mask, 1] = colour[1]
    img[mask, 2] = colour[2]
    img[:, :, 3]  = alpha
    return Image.fromarray(img, "RGBA")


# ---------------------------------------------------------------------------
# Shape generators
# ---------------------------------------------------------------------------

def circle_frame(colour: tuple) -> Image.Image:
    """Draw a circular ring using smooth distance-based alpha.

    The outer and inner edges are each feathered by ±1.5 px so the frame
    composites cleanly against any background without aliasing artefacts.
    """
    y, x   = np.ogrid[:SIZE, :SIZE]
    dist   = np.sqrt((x - CX) ** 2 + (y - CY) ** 2).astype(np.float32)
    outer_r = CX - 12
    inner_r = outer_r - BORDER

    outer_a = np.clip(outer_r + 1.5 - dist, 0.0, 1.0)
    inner_a = np.clip(dist - inner_r + 1.5, 0.0, 1.0)
    alpha   = (outer_a * inner_a * 255).astype(np.uint8)
    return _assemble(alpha, colour)


def square_frame(colour: tuple) -> Image.Image:
    """Draw a square ring with rounded corners using a signed-distance field.

    The SDF for a rounded rectangle produces perfectly smooth diagonal joins
    at the corners without any maths artefacts or pixel gaps.
    """
    y, x   = np.ogrid[:SIZE, :SIZE]
    dx = np.abs(x - CX).astype(np.float32)
    dy = np.abs(y - CY).astype(np.float32)

    outer_h = float(CX - 12)   # outer half-extent
    inner_h = outer_h - BORDER  # inner half-extent
    corner_r = 22.0              # corner radius (same for inner and outer)

    def sdf_rrect(dx: np.ndarray, dy: np.ndarray, half: float, r: float) -> np.ndarray:
        """Inigo Quilez-style 2-D rounded-rectangle SDF.

        Returns negative values inside the shape and positive outside.
        The corner radius r creates a smooth quarter-circle at each corner.
        """
        qx = np.maximum(dx - (half - r), 0.0)
        qy = np.maximum(dy - (half - r), 0.0)
        return np.sqrt(qx ** 2 + qy ** 2) - r

    outer_sdf = sdf_rrect(dx, dy, outer_h, corner_r)
    inner_sdf = sdf_rrect(dx, dy, inner_h, corner_r)

    # Frame lives where we are inside the outer shape AND outside the inner shape
    outer_a = np.clip(0.5 - outer_sdf, 0.0, 1.0)
    inner_a = np.clip(0.5 + inner_sdf, 0.0, 1.0)
    alpha   = (outer_a * inner_a * 255).astype(np.uint8)
    return _assemble(alpha, colour)


def hex_frame(colour: tuple) -> Image.Image:
    """Draw a pointy-top hexagonal ring (vertex at top/bottom, flat edges left/right).

    Uses the three-half-plane definition of a regular hexagon derived from face
    normals at 0°, 60°, and 120°.  The boolean inner/outer masks are softened
    with _soft_alpha() to remove aliasing along the six edges.
    """
    y, x   = np.ogrid[:SIZE, :SIZE]
    dx = (x - CX).astype(np.float32)
    dy = (y - CY).astype(np.float32)
    sq3 = float(np.sqrt(3))

    def in_hex(R: float) -> np.ndarray:
        """Return a boolean mask: True for every pixel inside a pointy-top hex
        with circumradius R (centre to vertex).

        Derived from the three face-normal conditions for a pointy-top regular
        hexagon with inradius a = R*√3/2:
          |dx|              <= a
          |dx + dy*√3|      <= 2a  (upper-right and lower-left faces)
          |dx − dy*√3|      <= 2a  (upper-left and lower-right faces)
        """
        a = R * sq3 / 2.0
        c1 = np.abs(dx) <= a
        c2 = np.abs(dx + dy * sq3) <= 2.0 * a
        c3 = np.abs(dx - dy * sq3) <= 2.0 * a
        return c1 & c2 & c3

    outer_R = float(CX - 12)
    inner_R = outer_R - BORDER

    frame_mask = in_hex(outer_R) & ~in_hex(inner_R)
    alpha = _soft_alpha(frame_mask)
    return _assemble(alpha, colour)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

GENERATORS = {
    "circle": circle_frame,
    "square": square_frame,
    "hex":    hex_frame,
}

if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0

    for shape, gen in GENERATORS.items():
        for colour_name, colour in COLOURS.items():
            filename = f"frame_{shape}_{colour_name}.png"
            path     = os.path.join(OUT_DIR, filename)
            img      = gen(colour)
            img.save(path, "PNG")
            print(f"  {filename}")
            total += 1

    print(f"\n{total} frames saved to:\n  {OUT_DIR}")
