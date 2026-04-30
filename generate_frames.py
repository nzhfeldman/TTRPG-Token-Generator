"""
generate_frames.py  —  RPG Token Frame Generator
Generates all token frame PNGs: plain colour frames + decorative frames.
Output: Frames/frame_{shape}_{pattern}.png

Run from the Token Generator folder:
    python generate_frames.py
"""

import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Frames")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SIZE   = 512
CENTER = SIZE // 2

RING_THICK = 60       # pixels; used for all shapes
CORNER_R   = 12       # inner corner radius for square frames


# ------------------------------------------------------------------
# Value noise and Fractional Brownian Motion
# ------------------------------------------------------------------

_GRID_CACHE: dict = {}


def _make_grid(n: int, seed: int) -> np.ndarray:
    """(n+1)×(n+1) random value grid in [0,1], cached by (n, seed)."""
    key = (n, seed)
    if key not in _GRID_CACHE:
        _GRID_CACHE[key] = np.random.default_rng(seed).random((n + 1, n + 1)).astype(np.float32)
    return _GRID_CACHE[key]


def _bilinear(grid: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Sample a value-noise grid at float coords u, v with smoothstep interpolation."""
    n = grid.shape[0] - 1
    u = np.clip(u, 0.0, float(n) - 1e-5)
    v = np.clip(v, 0.0, float(n) - 1e-5)
    xi = u.astype(np.int32)
    yi = v.astype(np.int32)
    xf = u - xi;  sx = xf * xf * (3.0 - 2.0 * xf)
    yf = v - yi;  sy = yf * yf * (3.0 - 2.0 * yf)
    xi1 = xi + 1
    yi1 = yi + 1
    return (grid[yi,  xi ] * (1.0 - sx) * (1.0 - sy)
          + grid[yi,  xi1] *        sx   * (1.0 - sy)
          + grid[yi1, xi ] * (1.0 - sx) *        sy
          + grid[yi1, xi1] *        sx   *        sy).astype(np.float32)


def fbm2d(n: int, seed: int, octaves: int = 6,
          lacunarity: float = 2.0, gain: float = 0.5,
          ox: np.ndarray = None, oy: np.ndarray = None) -> np.ndarray:
    """Fractional Brownian Motion over a SIZE×SIZE grid.

    n        : base grid resolution (cells). Larger n = finer base features.
    ox, oy   : per-pixel displacement maps (pixel units) for domain warping.
    Returns float32 (SIZE, SIZE) normalised to [0, 1].
    """
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]
    px = xx.astype(np.float32) + (ox if ox is not None else 0.0)
    py = yy.astype(np.float32) + (oy if oy is not None else 0.0)

    result    = np.zeros((SIZE, SIZE), dtype=np.float32)
    amplitude = 0.5
    norm      = 0.0
    freq      = 1.0

    for i in range(octaves):
        ni   = max(2, min(SIZE, int(round(n * freq))))
        grid = _make_grid(ni, seed + i * 6271)
        sc   = ni / float(SIZE)
        result   += amplitude * _bilinear(grid, px * sc, py * sc)
        norm      += amplitude
        amplitude *= gain
        freq      *= lacunarity

    return (result / norm).astype(np.float32)


# ------------------------------------------------------------------
# Shape masks  —  returns uint8 (SIZE,SIZE), 255=ring, 0=transparent
# ------------------------------------------------------------------

def _circle_mask(outer_r: float, inner_r: float) -> np.ndarray:
    img = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(img)
    cx = cy = CENTER
    d.ellipse([cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r], fill=255)
    d.ellipse([cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r], fill=0)
    return np.array(img, dtype=np.uint8)


def _hex_mask(outer_r: float, inner_r: float) -> np.ndarray:
    def pts(r):
        return [(CENTER + r * math.cos(math.radians(60 * i)),
                 CENTER + r * math.sin(math.radians(60 * i))) for i in range(6)]
    o = Image.new("L", (SIZE, SIZE), 0); ImageDraw.Draw(o).polygon(pts(outer_r), fill=255)
    i = Image.new("L", (SIZE, SIZE), 0); ImageDraw.Draw(i).polygon(pts(inner_r), fill=255)
    return np.clip(np.array(o).astype(int) - np.array(i).astype(int), 0, 255).astype(np.uint8)


def _square_mask(outer_pad: int, inner_pad: int) -> np.ndarray:
    def rr(pad, cr):
        img = Image.new("L", (SIZE, SIZE), 0)
        ImageDraw.Draw(img).rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=cr, fill=255)
        return np.array(img, dtype=np.uint8)
    return np.clip(rr(outer_pad, CORNER_R + 8).astype(int) - rr(inner_pad, CORNER_R).astype(int), 0, 255).astype(np.uint8)


def get_ring_mask(shape: str) -> np.ndarray:
    outer = CENTER - 20
    inner = outer - RING_THICK
    if shape == "circle":
        raw = _circle_mask(outer, inner)
    elif shape == "hex":
        raw = _hex_mask(outer, inner)
    else:  # square
        raw = _square_mask(20, 20 + RING_THICK)
    # Soft anti-alias edge
    soft = Image.fromarray(raw, "L").filter(ImageFilter.GaussianBlur(radius=0.8))
    return np.array(soft, dtype=np.uint8)


# ------------------------------------------------------------------
# Coordinate helpers
# ------------------------------------------------------------------

def polar_coords() -> tuple[np.ndarray, np.ndarray]:
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    dx, dy = x - CENTER, y - CENTER
    return np.arctan2(dy, dx), np.sqrt(dx ** 2 + dy ** 2)


def warped_polar(seed: int) -> tuple[np.ndarray, np.ndarray]:
    """Polar coords displaced by FBM domain warping: fbm(p + fbm(p))."""
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]

    # First warp layer: plain FBM gives a coarse displacement field q
    q_x = (fbm2d(5, seed,     octaves=4) - 0.5) * 2.0
    q_y = (fbm2d(5, seed + 1, octaves=4) - 0.5) * 2.0

    # Second layer sampled at p + q*scale — the domain warp itself
    WARP_PX = 38.0
    r_x = (fbm2d(5, seed + 2, octaves=4, ox=q_x * WARP_PX, oy=q_y * WARP_PX) - 0.5) * 56.0
    r_y = (fbm2d(5, seed + 3, octaves=4, ox=q_x * WARP_PX, oy=q_y * WARP_PX) - 0.5) * 56.0

    xw = np.clip(xx.astype(np.float32) + r_x, 0, SIZE - 1)
    yw = np.clip(yy.astype(np.float32) + r_y, 0, SIZE - 1)
    dx, dy = xw - CENTER, yw - CENTER
    return np.arctan2(dy, dx), np.sqrt(dx ** 2 + dy ** 2)


# ------------------------------------------------------------------
# Texture generators — each returns (SIZE,SIZE,4) uint8 RGBA
# All pixels set to alpha=255; the ring mask is applied afterwards.
# ------------------------------------------------------------------

# ── Plain colour ──────────────────────────────────────────────────

def gen_solid(r: float, g: float, b: float) -> np.ndarray:
    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[:, :, 0] = int(r * 255)
    rgba[:, :, 1] = int(g * 255)
    rgba[:, :, 2] = int(b * 255)
    rgba[:, :, 3] = 255
    return rgba


# ── Bamboo ────────────────────────────────────────────────────────

def gen_bamboo() -> np.ndarray:
    angle, radius = polar_coords()
    arc = angle * radius
    node_spacing = 80.0          # wider segments
    t = (arc % node_spacing) / node_spacing
    # Wider node bands: sigma raised from 0.003 → 0.018
    node_band = np.exp(-(t ** 2) / 0.018) + np.exp(-((t - 1.0) ** 2) / 0.018)
    node_band = np.clip(node_band, 0, 1)

    n1 = fbm2d(128, 42)
    n2 = fbm2d(43,  43)
    grain = 0.5 + 0.35 * np.sin(radius * 0.7 + n1 * 8) + 0.15 * n2

    base_r = np.full((SIZE, SIZE), 0.42, dtype=np.float32)
    base_g = np.full((SIZE, SIZE), 0.63, dtype=np.float32)
    base_b = np.full((SIZE, SIZE), 0.18, dtype=np.float32)

    dark = 1.0 - 0.50 * node_band
    streak = fbm2d(85, 44)
    r = np.clip(base_r * grain * dark + 0.08 * streak, 0, 1)
    g = np.clip(base_g * grain * dark + 0.14 * streak, 0, 1)
    b = np.clip(base_b * grain * dark, 0, 1)

    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[:, :, 0] = (r * 255).astype(np.uint8)
    rgba[:, :, 1] = (g * 255).astype(np.uint8)
    rgba[:, :, 2] = (b * 255).astype(np.uint8)
    rgba[:, :, 3] = 255
    return rgba


# ── Dark wood with leaves ─────────────────────────────────────────

def gen_darkwoodwithleaves() -> np.ndarray:
    _, radius = polar_coords()
    n1 = fbm2d(51,  10)
    n2 = fbm2d(128, 11)

    # Wider grain: lower frequency (2.0 vs old 5.0)
    y, x = np.mgrid[0:SIZE, 0:SIZE]
    wobble = fbm2d(64, 12) * 20
    grain_raw = np.sin(2.0 * (x * 0.98 + y * 0.18) / SIZE * 2 * math.pi * 8 + wobble * 4)
    grain = (grain_raw + 1) / 2
    grain = grain * 0.55 + n1 * 0.35 + n2 * 0.10

    base_r = 0.28 + 0.20 * grain
    base_g = 0.14 + 0.11 * grain
    base_b = 0.06 + 0.06 * grain

    # Leaf blobs around the ring midpoint
    leaf = np.zeros((SIZE, SIZE), dtype=np.float32)
    mid_r = CENTER - 50
    for a in np.linspace(-math.pi, math.pi, 18, endpoint=False):
        lx = CENTER + mid_r * math.cos(a)
        ly = CENTER + mid_r * math.sin(a)
        dx = (x - lx) * math.cos(a) + (y - ly) * math.sin(a)
        dy = -(x - lx) * math.sin(a) + (y - ly) * math.cos(a)
        leaf = np.maximum(leaf, np.exp(-(dx ** 2) / 55 - (dy ** 2) / 14))

    r = np.clip(base_r - 0.06 * leaf, 0, 1)
    g = np.clip(base_g + 0.14 * leaf, 0, 1)
    b = np.clip(base_b + 0.05 * leaf, 0, 1)

    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[:, :, 0] = (r * 255).astype(np.uint8)
    rgba[:, :, 1] = (g * 255).astype(np.uint8)
    rgba[:, :, 2] = (b * 255).astype(np.uint8)
    rgba[:, :, 3] = 255
    return rgba


# ── Metallic (base) ───────────────────────────────────────────────

def gen_metallic(
    base_rgb: tuple, highlight_rgb: tuple, shadow_rgb: tuple, seed: int = 20
) -> np.ndarray:
    """Metallic ring with FBM domain-warp distortion (bent/used look)."""
    angle, radius = warped_polar(seed)  # warped coords give bent-metal feel
    n1 = fbm2d(85,  seed + 4)
    n2 = fbm2d(256, seed + 5)

    # Angular brushing streaks running along the warped ring surface
    brush = 0.5 * np.sin(angle * 55 + n1 * 3.5) + 0.5

    # Highlight near top, shadow near bottom (in warped space)
    highlight_a = -math.pi / 2
    ad = np.abs(angle - highlight_a)
    ad = np.minimum(ad, 2 * math.pi - ad)
    highlight = np.exp(-(ad ** 2) / 0.28)

    shadow_a = math.pi / 2
    sd = np.abs(angle - shadow_a)
    sd = np.minimum(sd, 2 * math.pi - sd)
    shadow = np.exp(-(sd ** 2) / 0.5)

    # Surface dents: small-scale radial variation from the warp
    dent = fbm2d(43, seed + 6) * 0.12

    br, bg, bb = base_rgb
    hr, hg, hb = highlight_rgb
    sr, sg, sb = shadow_rgb

    mix = brush * 0.20 + n2 * 0.06 + dent
    r = np.clip(br + (hr - br) * highlight * 0.72 + (sr - br) * shadow * 0.40 + mix * 0.06, 0, 1)
    g = np.clip(bg + (hg - bg) * highlight * 0.72 + (sg - bg) * shadow * 0.40 + mix * 0.06, 0, 1)
    b = np.clip(bb + (hb - bb) * highlight * 0.72 + (sb - bb) * shadow * 0.40 + mix * 0.06, 0, 1)

    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[:, :, 0] = (r * 255).astype(np.uint8)
    rgba[:, :, 1] = (g * 255).astype(np.uint8)
    rgba[:, :, 2] = (b * 255).astype(np.uint8)
    rgba[:, :, 3] = 255
    return rgba


def gen_metallicbronze() -> np.ndarray:
    return gen_metallic((0.60, 0.38, 0.18), (0.95, 0.75, 0.45), (0.30, 0.18, 0.07), seed=20)

def gen_metallicSilver() -> np.ndarray:
    return gen_metallic((0.62, 0.64, 0.67), (0.95, 0.97, 1.00), (0.28, 0.30, 0.33), seed=30)

def gen_metallicgold() -> np.ndarray:
    return gen_metallic((0.72, 0.58, 0.12), (1.00, 0.95, 0.60), (0.38, 0.28, 0.04), seed=40)


# ── Corrosion modifier ────────────────────────────────────────────

def _smin(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Quadratic smooth-minimum — smooth union of two signed-distance fields.

    At k=0 this degenerates to ordinary min().  For k>0 the junction between
    two SDF shapes is replaced with a rounded fillet of approximate radius k/2.
    All ops are vectorised numpy; no transcendentals required.
    """
    h = np.maximum(k - np.abs(a - b), 0.0)
    return np.minimum(a, b) - h * h * 0.25 / k


def apply_corrosion(base_fn, corrosion_rgb: tuple, seed: int,
                    opacity_mode: str = 'noise') -> np.ndarray:
    """Drip-based corrosion with domain-warped SDFs and smooth circle→triangle blend.

    opacity_mode: 'sinwave' (4 sin waves) | 'noise' (smoothed uniform noise)
    """

    rng = np.random.default_rng(seed)

    # ------------------------------------------------------------------
    # Step 1 — Ring mask
    # ------------------------------------------------------------------
    inner_r = (CENTER - 20) - RING_THICK
    outer_r = CENTER - 20

    _, radius = polar_coords()
    ring_pixels = (radius >= inner_r) & (radius <= outer_r)
    total_ring  = np.count_nonzero(ring_pixels)

    # ------------------------------------------------------------------
    # Step 2 — Domain warp field (computed ONCE; shared by every drip)
    # FBM domain warping fbm(p + fbm(p)): coarse q layer steers the large
    # liquid flows; warped r layer adds fine surface-tension ripples.
    # ------------------------------------------------------------------
    yy, xx = np.mgrid[0:SIZE, 0:SIZE]

    q_x = (fbm2d(10, seed + 1000, octaves=4) - 0.5) * 2.0
    q_y = (fbm2d(10, seed + 1002, octaves=4) - 0.5) * 2.0
    WARP_PX = 30.0
    wx  = (fbm2d(10, seed + 1001, octaves=4, ox=q_x * WARP_PX, oy=q_y * WARP_PX) - 0.5) * 60.0
    wy  = (fbm2d(10, seed + 1003, octaves=4, ox=q_x * WARP_PX, oy=q_y * WARP_PX) - 0.5) * 60.0
    xxw = np.clip((xx + wx).astype(np.float32), 0.0, SIZE - 1.0)
    yyw = np.clip((yy + wy).astype(np.float32), 0.0, SIZE - 1.0)

    # Edge function evaluated on the warped grid (reused for every drip).
    def _edge_w(p1x, p1y, p2x, p2y):
        return (xxw - p1x) * (p2y - p1y) - (yyw - p1y) * (p2x - p1x)

    # ------------------------------------------------------------------
    # Generate drips in batches of 3, stop at 40% ring coverage
    # ------------------------------------------------------------------
    drip_alpha = np.zeros((SIZE, SIZE), dtype=np.float32)
    drip_color = np.zeros((SIZE, SIZE, 3), dtype=np.float32)
    total_drips      = 0
    covered_fraction = 0.0

    SMIN_K = 10.0   # fillet radius (px) at the circle→triangle junction

    while covered_fraction <= 0.40 and total_drips < 200:
        for _ in range(3):
            if total_drips >= 200:
                break

            # Sample drip centre within the ring band
            angle  = rng.uniform(-math.pi, math.pi)
            r_samp = rng.uniform(inner_r, outer_r)
            cx = CENTER + r_samp * math.cos(angle)
            cy = CENTER + r_samp * math.sin(angle)

            r_drip = rng.uniform(48, 96)

            # Per-drip local transform: x-scale + rotation applied BEFORE domain warp.
            # Rotates/squashes the drip shape in local space for organic variety.
            sx      = rng.uniform(0.9, 1.1)          # x-axis scale
            theta   = rng.uniform(-20.0, 20.0) * math.pi / 180.0
            cos_t, sin_t = math.cos(theta), math.sin(theta)

            # Local warped offsets from drip centre
            dlx = xxw - cx
            dly = yyw - cy
            # Inverse transform (rotate then scale) maps world→local-drip space
            lx = ( dlx * cos_t + dly * sin_t) / sx
            ly = (-dlx * sin_t + dly * cos_t)

            # Perturbed colour — shared luminance delta keeps grey colours grey;
            # small independent hue deltas add variety to saturated metals.
            lum_delta = rng.uniform(-0.10, 0.10)
            hue_delta = rng.uniform(-0.06, 0.06, size=3)
            drip_col = np.array([
                float(np.clip(corrosion_rgb[0] + lum_delta + hue_delta[0], 0.0, 1.0)),
                float(np.clip(corrosion_rgb[1] + lum_delta + hue_delta[1], 0.0, 1.0)),
                float(np.clip(corrosion_rgb[2] + lum_delta + hue_delta[2], 0.0, 1.0)),
            ], dtype=np.float32)

            # Tip offset defined in local-drip space, then kept local.
            dx_tip_l = rng.uniform(-1.2, 1.2) * r_drip
            dy_tip_l = rng.uniform(2.0,  3.0) * r_drip

            # ---- Circle SDF in local-drip space ----
            sdf_c = np.sqrt(lx ** 2 + ly ** 2) - r_drip

            # ---- Triangle SDF in local-drip space ----
            # Vertices in local space (A left, B right, T tip — all relative to origin).
            ax_l, ay_l =  -r_drip, 0.0
            bx_l, by_l =   r_drip, 0.0
            tx_l, ty_l = dx_tip_l, dy_tip_l

            len_AB = max(math.hypot(bx_l - ax_l, by_l - ay_l), 1.0)
            len_BC = max(math.hypot(tx_l - bx_l, ty_l - by_l), 1.0)
            len_CA = max(math.hypot(ax_l - tx_l, ay_l - ty_l), 1.0)

            # Edge functions in local pixel-unit signed distances.
            def _edge_l(p1x, p1y, p2x, p2y):
                return (lx - p1x) * (p2y - p1y) - (ly - p1y) * (p2x - p1x)

            d0 = _edge_l(ax_l, ay_l, bx_l, by_l) / len_AB
            d1 = _edge_l(bx_l, by_l, tx_l, ty_l) / len_BC
            d2 = _edge_l(tx_l, ty_l, ax_l, ay_l) / len_CA
            sdf_t = np.maximum(d0, np.maximum(d1, d2))

            # ---- Smooth union via smin ----
            # The fillet radius k melts the hard corner where circle meets triangle.
            sdf_blend  = _smin(sdf_c, sdf_t, SMIN_K)
            layer_alpha = (sdf_blend <= 0.0).astype(np.float32)

            update = layer_alpha > drip_alpha
            drip_color[update] = drip_col
            drip_alpha = np.where(layer_alpha > drip_alpha, layer_alpha, drip_alpha)

            total_drips += 1

        covered = np.count_nonzero((drip_alpha > 0.05) & ring_pixels)
        covered_fraction = covered / max(total_ring, 1)

    # ------------------------------------------------------------------
    # Step 3 — Smooth drip edges to look liquid
    # ------------------------------------------------------------------
    alpha_img = Image.fromarray((drip_alpha * 255).astype(np.uint8), "L")
    alpha_img = alpha_img.filter(ImageFilter.GaussianBlur(radius=2.5))
    drip_alpha_smooth = np.array(alpha_img, dtype=np.float32) / 255.0

    # Add FBM perturbation for ragged liquid edge
    noise_layer = fbm2d(85, seed + 100) * 0.3
    drip_alpha_smooth = np.clip(drip_alpha_smooth + noise_layer, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Step 4 — Drip opacity field
    # ------------------------------------------------------------------
    if opacity_mode == 'sinwave':
        # 4 sin waves: 2 vertical (y-axis), 2 horizontal (x-axis).
        # Each pair has one low-freq (~5) and one high-freq (~50) wave,
        # sampled independently. sum/8 + 0.5 maps [-4,4] → [0,1].
        fvl = rng.uniform(4.0, 6.0)    # vertical low
        fvh = rng.uniform(47.0, 53.0)  # vertical high
        fhl = rng.uniform(4.0, 6.0)    # horizontal low
        fhh = rng.uniform(47.0, 53.0)  # horizontal high
        wave = (np.sin(2.0 * math.pi * fvl * yy / SIZE) +
                np.sin(2.0 * math.pi * fvh * yy / SIZE) +
                np.sin(2.0 * math.pi * fhl * xx / SIZE) +
                np.sin(2.0 * math.pi * fhh * xx / SIZE))
        drip_opacity = (wave / 8.0 + 0.5).astype(np.float32)
    else:
        # 'noise': smoothed uniform noise (original method)
        raw_noise = rng.uniform(0.40, 0.90, (SIZE, SIZE)).astype(np.float32)
        try:
            from scipy.ndimage import uniform_filter
            drip_opacity = uniform_filter(raw_noise, size=5)
        except ImportError:
            k = np.ones(5, dtype=np.float32) / 5.0
            tmp = np.apply_along_axis(lambda row: np.convolve(row, k, mode='same'), 1, raw_noise)
            drip_opacity = np.apply_along_axis(lambda col: np.convolve(col, k, mode='same'), 0, tmp)
        drip_opacity = drip_opacity.astype(np.float32)

    # ------------------------------------------------------------------
    # Step 5 — Composite drips over base
    # ------------------------------------------------------------------
    base = base_fn().astype(np.float32) / 255.0

    final_alpha = drip_alpha_smooth * drip_opacity  # (SIZE, SIZE)

    # Expand dims for broadcasting over RGB channels
    fa = final_alpha[:, :, np.newaxis]

    out_color = base[:, :, :3] * (1.0 - fa) + drip_color * fa
    out_color = np.clip(out_color, 0.0, 1.0)

    rgba = np.zeros((SIZE, SIZE, 4), dtype=np.uint8)
    rgba[:, :, 0] = (out_color[:, :, 0] * 255).astype(np.uint8)
    rgba[:, :, 1] = (out_color[:, :, 1] * 255).astype(np.uint8)
    rgba[:, :, 2] = (out_color[:, :, 2] * 255).astype(np.uint8)
    rgba[:, :, 3] = 255
    return rgba


def gen_metallicbronzecorroded(seed: int = 77) -> np.ndarray:
    # Bronze corrodes to emerald green verdigris
    return apply_corrosion(gen_metallicbronze, (0.08, 0.61, 0.35), seed=seed)

def gen_metallicSilvercorroded(seed: int = 88) -> np.ndarray:
    # Silver tarnishes to neutral dark grey (unsaturated)
    return apply_corrosion(gen_metallicSilver, (0.15, 0.15, 0.15), seed=seed)

def gen_metallicgoldcorroded(seed: int = 99) -> np.ndarray:
    # Gold bleeds vibrant red
    return apply_corrosion(gen_metallicgold, (0.85, 0.08, 0.05), seed=seed)


# ------------------------------------------------------------------
# Pattern registry
# ------------------------------------------------------------------

PLAIN_COLORS = {
    "beige": (0.780, 0.686, 0.533),
    "black": (0.118, 0.118, 0.118),
    "blue":  (0.180, 0.420, 0.780),
    "green": (0.200, 0.560, 0.260),
    "red":   (0.720, 0.180, 0.160),
    "white": (0.900, 0.900, 0.900),
}

FANCY_PATTERNS = {
    "bamboo":                gen_bamboo,
    "darkwoodwithleaves":    gen_darkwoodwithleaves,
    "metallicbronze":        gen_metallicbronze,
    "metallicbronzecorroded": gen_metallicbronzecorroded,
    "metallicSilver":        gen_metallicSilver,
    "metallicSilvercorroded": gen_metallicSilvercorroded,
    "metallicgold":          gen_metallicgold,
    "metallicgoldcorroded":  gen_metallicgoldcorroded,
}

SHAPES = ["circle", "hex", "square"]

# Base seeds for corrosion patterns. Each shape gets base_seed + shape_index*997
# so drip layouts differ between circle / hex / square versions of the same pattern.
CORROSION_BASE_SEEDS = {
    "metallicbronzecorroded": 77,
    "metallicSilvercorroded": 88,
    "metallicgoldcorroded":   99,
}


# ------------------------------------------------------------------
# Frame assembly
# ------------------------------------------------------------------

def apply_mask(texture: np.ndarray, ring_mask: np.ndarray) -> np.ndarray:
    out = texture.copy()
    out[:, :, 3] = ring_mask
    return out


def save_frame(shape: str, pattern: str, texture: np.ndarray):
    mask = get_ring_mask(shape)
    result = apply_mask(texture, mask)
    path = os.path.join(OUTPUT_DIR, f"frame_{shape}_{pattern}.png")
    Image.fromarray(result, "RGBA").save(path, "PNG")
    print(f"  Saved: frame_{shape}_{pattern}.png")


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    count = 0

    print("-- Plain colour frames --------------------------------------")
    for pattern, (r, g, b) in PLAIN_COLORS.items():
        texture = gen_solid(r, g, b)
        for shape in SHAPES:
            save_frame(shape, pattern, texture)
            count += 1

    print("\n-- Decorative frames ----------------------------------------")
    for pattern, gen_fn in FANCY_PATTERNS.items():
        base_seed = CORROSION_BASE_SEEDS.get(pattern)
        for i, shape in enumerate(SHAPES):
            # Corrosion patterns get a unique seed per shape so drip layouts differ.
            # All other patterns generate once and are deterministic anyway.
            if base_seed is not None:
                texture = gen_fn(seed=base_seed + i * 997)
            else:
                texture = gen_fn()
            save_frame(shape, pattern, texture)
            count += 1

    print(f"\nDone. {count} frames written to:\n  {OUTPUT_DIR}")
