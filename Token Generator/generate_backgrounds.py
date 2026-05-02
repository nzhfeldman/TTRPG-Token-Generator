"""
generate_backgrounds.py  —  RPG Token Background Generator
Generates chunky pixel-art background PNGs for the token generator.
Output: Backgrounds/bg_{name}.png

Run from the Token Generator folder:
    python generate_backgrounds.py
"""

import os
import math
import numpy as np
from PIL import Image

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Backgrounds")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SIZE  = 512
PIXEL = 8
G     = SIZE // PIXEL   # 64 — working grid


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def canvas() -> np.ndarray:
    return np.zeros((G, G, 4), dtype=np.uint8)


def rect(buf: np.ndarray, x: int, y: int, w: int, h: int, c: tuple):
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(G, x + w), min(G, y + h)
    if x1 > x0 and y1 > y0:
        buf[y0:y1, x0:x1] = c


def sky_fill(buf: np.ndarray, top: tuple, bot: tuple, rows: int = G):
    for y in range(min(rows, G)):
        t = y / max(rows - 1, 1)
        buf[y, :] = (
            int(top[0] + (bot[0] - top[0]) * t),
            int(top[1] + (bot[1] - top[1]) * t),
            int(top[2] + (bot[2] - top[2]) * t),
            255,
        )


def wavy(base: int, amp: float, freq: float, phase: float = 0.0) -> list:
    return [int(round(base + amp * math.sin(x * freq + phase))) for x in range(G)]


def fill_below(buf: np.ndarray, horizon: list, color: tuple):
    for x in range(G):
        y = max(0, min(G, horizon[x]))
        buf[y:, x] = color


def cloud(buf: np.ndarray, cx: int, cy: int, w: int, h: int, c: tuple, shadow: tuple):
    rect(buf, cx, cy, w, h, c)
    rect(buf, cx + 1, cy + h, w - 2, 1, shadow)


def pine_tree(buf: np.ndarray, cx: int, gy: int, c_trunk: tuple, c_leaf: tuple):
    """Pixel-art pine. gy = ground row the trunk stands on."""
    for dy in range(2):
        y = gy - dy
        if 0 <= y < G and 0 <= cx < G:
            buf[y, cx] = c_trunk
    for i, w in enumerate([1, 3, 5, 7]):
        y = gy - 5 + i
        if 0 <= y < G:
            buf[y, max(0, cx - w // 2):min(G, cx + w // 2 + 1)] = c_leaf


def triangle_peak(buf: np.ndarray, px: int, top_y: int, bot_y: int,
                  hw: int, fill: tuple, snow_rows: int = 0, snow: tuple = None):
    for y in range(top_y, bot_y + 1):
        if not (0 <= y < G):
            continue
        prog = (y - top_y) / max(bot_y - top_y, 1)
        w = int(hw * prog)
        x0, x1 = max(0, px - w), min(G, px + w + 1)
        c = snow if (snow and y < top_y + snow_rows) else fill
        buf[y, x0:x1] = c


# ---------------------------------------------------------------------------
# Backgrounds
# ---------------------------------------------------------------------------

def gen_grassland() -> np.ndarray:
    buf = canvas()
    SKY_T = ( 82, 146, 218, 255);  SKY_B = (132, 190, 236, 255)
    CLD   = (244, 248, 252, 255);  CLDS  = (192, 212, 232, 255)
    GND_D = ( 60, 106,  30, 255);  GND   = ( 86, 140,  40, 255)
    GND_L = (116, 172,  50, 255)
    FLWR  = (214,  70,  58, 255);  FLWY  = (234, 206,  52, 255)

    sky_fill(buf, SKY_T, SKY_B)
    h = wavy(37, 2.5, 0.38, 0.0)

    for x in range(G):
        hy = h[x]
        for y in range(hy, G):
            d = y - hy
            if d == 0:
                buf[y, x] = GND_L
            elif d < 4:
                buf[y, x] = GND_L if (x + y) % 3 else GND
            elif (x * 3 + y * 2) % 9 < 2:
                buf[y, x] = GND_D
            else:
                buf[y, x] = GND

    # Grass tufts — 1 px spikes above horizon
    for x in range(0, G, 3):
        ty = h[x] - 1
        if 0 <= ty < G:
            buf[ty, x] = GND_L

    cloud(buf,  7, 10, 12, 3, CLD, CLDS)
    cloud(buf, 11, 12,  7, 2, CLD, CLDS)
    cloud(buf, 33,  7, 14, 3, CLD, CLDS)
    cloud(buf, 37,  9,  8, 2, CLD, CLDS)
    cloud(buf, 52, 14,  9, 3, CLD, CLDS)

    for fx, fy, fc in [
        (11, 44, FLWR), (19, 52, FLWY), (27, 41, FLWR), (34, 57, FLWY),
        (41, 46, FLWR), (49, 53, FLWY), ( 9, 58, FLWY), (43, 60, FLWR),
        (56, 43, FLWR), (23, 61, FLWY), ( 5, 47, FLWY), (59, 56, FLWR),
    ]:
        buf[fy, fx] = fc

    return buf


def gen_hills() -> np.ndarray:
    buf = canvas()
    SKY_T = ( 98, 158, 222, 255);  SKY_B = (152, 202, 238, 255)
    CLD   = (244, 248, 252, 255);  CLDS  = (192, 214, 234, 255)
    HFAR  = ( 78, 128,  78, 255)   # far hills — muted green
    HMID  = ( 62, 118,  42, 255)   # mid hills
    HNEAR = ( 44,  96,  24, 255)   # near hills — darkest
    TRUNK = ( 72,  48,  22, 255)
    LEAF  = ( 32,  76,  18, 255);  LEAFL = ( 52, 106,  28, 255)

    sky_fill(buf, SKY_T, SKY_B)

    hfar  = wavy(27, 5.0, 0.22, 1.2)
    hmid  = wavy(35, 4.0, 0.30, 0.4)
    hnear = wavy(44, 3.5, 0.42, 2.0)

    fill_below(buf, hfar,  HFAR)
    fill_below(buf, hmid,  HMID)
    fill_below(buf, hnear, HNEAR)

    cloud(buf,  9,  8, 11, 3, CLD, CLDS)
    cloud(buf, 13,  9,  6, 2, CLD, CLDS)
    cloud(buf, 41,  6, 13, 3, CLD, CLDS)
    cloud(buf, 45,  8,  7, 2, CLD, CLDS)

    for tx in [4, 9, 16, 23, 30, 39, 46, 53, 59]:
        gy = hmid[min(tx, G - 1)]
        pine_tree(buf, tx, gy, TRUNK, LEAF if tx % 2 else LEAFL)

    return buf


def gen_mountains() -> np.ndarray:
    buf = canvas()
    SKY_T  = ( 68, 118, 198, 255);  SKY_B  = (152, 196, 226, 255)
    CLD    = (238, 244, 250, 255);  CLDS   = (182, 202, 224, 255)
    ROCK_D = ( 72,  68,  82, 255);  ROCK   = (108, 102, 118, 255)
    ROCK_L = (138, 132, 150, 255)
    SNOW   = (232, 236, 244, 255);  SNOWS  = (192, 198, 214, 255)
    PINE   = ( 30,  58,  26, 255);  PINE_L = ( 44,  82,  36, 255)
    GROUND = ( 54,  96,  28, 255);  TRUNK  = ( 58,  38,  18, 255)

    sky_fill(buf, SKY_T, SKY_B, rows=52)
    rect(buf, 0, 50, G, G - 50, GROUND)

    # Back peaks (lighter rock, small snow caps)
    for px, ty, by, hw, sr in [(10, 20, 50, 13, 3), (30, 14, 50, 15, 4), (50, 18, 50, 12, 3)]:
        triangle_peak(buf, px, ty, by, hw, ROCK, snow_rows=sr, snow=SNOW)

    # Front peaks (dark rock, bigger)
    for px, ty, by, hw, sr in [(16, 24, 63, 15, 5), (40, 17, 63, 20, 6), (60, 26, 63, 13, 4)]:
        triangle_peak(buf, px, ty, by, hw, ROCK_D, snow_rows=sr, snow=SNOW)
        # Left face highlight
        for y in range(ty, by + 1):
            if not (0 <= y < G):
                continue
            prog = (y - ty) / max(by - ty, 1)
            w = int(hw * prog)
            x0 = max(0, px - w)
            x1 = max(x0, min(G, px - w + max(1, w // 3)))
            buf[y, x0:x1] = SNOWS if y < ty + sr else ROCK_L

    # Scattered pines across lower half — jittered grid for natural clustering
    _rng = np.random.default_rng(7)
    for base_x in range(1, G, 5):
        tx = base_x + int(_rng.integers(-2, 3))
        gy = 49 + int(_rng.integers(0, 12))
        if 0 <= tx < G:
            pine_tree(buf, tx, gy, TRUNK, PINE if tx % 2 else PINE_L)

    cloud(buf,  4,  9, 12, 3, CLD, CLDS)
    cloud(buf, 42,  7, 11, 3, CLD, CLDS)

    return buf


def gen_beach() -> np.ndarray:
    buf = canvas()
    SKY_T = (108, 182, 236, 255);  SKY_B = (158, 212, 244, 255)
    CLD   = (246, 250, 254, 255);  CLDS  = (198, 218, 234, 255)
    OCN_D = ( 20,  94, 164, 255);  OCN   = ( 32, 126, 192, 255)
    OCN_L = ( 52, 152, 208, 255)
    FOAM  = (208, 236, 248, 255)
    SND_D = (202, 172, 114, 255);  SND   = (230, 202, 144, 255)
    SND_L = (246, 222, 172, 255)
    SHELL = (254, 244, 232, 255)

    sky_fill(buf, SKY_T, SKY_B)

    # Ocean band
    rect(buf, 0, 22, G, 16, OCN)
    for y in range(22, 38):
        for x in range(G):
            if (x + y * 3) % 8 < 2:
                buf[y, x] = OCN_D
            elif (x * 2 + y) % 7 == 0:
                buf[y, x] = OCN_L

    # Wave foam lines
    for base, amp, freq, phase in [(27, 1.0, 0.6, 0.0), (32, 1.2, 0.55, 1.2), (36, 0.8, 0.7, 2.5)]:
        wl = wavy(base, amp, freq, phase)
        for x in range(G):
            yy = wl[x]
            if 0 <= yy < G:
                buf[yy, x] = FOAM

    # Wet sand transition
    for x in range(G):
        buf[38, x] = SND_D if x % 3 else FOAM

    # Sand body
    for y in range(39, G):
        for x in range(G):
            if y < 43:
                buf[y, x] = SND_D if (x + y) % 4 < 2 else SND
            elif (x * 3 + y) % 11 < 2:
                buf[y, x] = SND_D
            elif (x + y * 2) % 9 == 0:
                buf[y, x] = SND_L
            else:
                buf[y, x] = SND

    for sx, sy in [(7, 46), (17, 53), (29, 44), (41, 57), (54, 48), (24, 61), (48, 52)]:
        buf[sy, sx] = SHELL

    cloud(buf, 11, 10, 11, 3, CLD, CLDS)
    cloud(buf, 43,  7, 13, 3, CLD, CLDS)

    return buf


def gen_ocean() -> np.ndarray:
    buf = canvas()
    SKY_T = ( 78, 138, 212, 255);  SKY_B = (128, 182, 236, 255)
    CLD   = (238, 244, 252, 255);  CLDS  = (178, 204, 228, 255)
    OCN_D = ( 10,  54, 134, 255);  OCN   = ( 20,  84, 164, 255)
    OCN_M = ( 32, 108, 182, 255);  OCN_L = ( 52, 136, 202, 255)
    FOAM  = (198, 228, 244, 255);  FOAML = (230, 246, 254, 255)

    sky_fill(buf, SKY_T, SKY_B, rows=16)

    # Horizon haze
    for y in range(14, 20):
        t = (y - 14) / 6.0
        buf[y, :] = (
            int(SKY_B[0] + (OCN[0] - SKY_B[0]) * t),
            int(SKY_B[1] + (OCN[1] - SKY_B[1]) * t),
            int(SKY_B[2] + (OCN[2] - SKY_B[2]) * t),
            255,
        )

    # Ocean body
    for y in range(20, G):
        t = (y - 20) / (G - 20)
        for x in range(G):
            if (x * 2 + y) % 11 < 2:
                buf[y, x] = OCN_D
            elif t > 0.45 and (x + y * 2) % 7 < 2:
                buf[y, x] = OCN_L
            elif (x * 3 + y) % 9 == 0:
                buf[y, x] = OCN_M
            else:
                buf[y, x] = OCN

    # Wave foam lines
    for base, amp, freq, phase, light in [
        (30, 1.2, 0.5, 0.0, False), (37, 1.5, 0.6, 1.3, False),
        (43, 1.3, 0.5, 2.8, False), (50, 1.8, 0.7, 0.7, False),
        (56, 1.5, 0.6, 1.9, False), (61, 1.0, 0.5, 3.5, True),
    ]:
        wl = wavy(base, amp, freq, phase)
        for x in range(G):
            yy = wl[x]
            if 0 <= yy < G:
                buf[yy, x] = FOAML if light else FOAM
            if 0 <= yy + 1 < G:
                buf[yy + 1, x] = OCN_L

    cloud(buf,  4,  5, 13, 3, CLD, CLDS)
    cloud(buf,  7,  7,  7, 2, CLD, CLDS)
    cloud(buf, 37,  4, 15, 3, CLD, CLDS)

    return buf


def gen_lake() -> np.ndarray:
    buf = canvas()
    SKY_T = ( 88, 152, 220, 255);  SKY_B = (142, 196, 238, 255)
    CLD   = (244, 248, 252, 255);  CLDS  = (192, 214, 234, 255)
    TRUNK = ( 62,  40,  16, 255)
    L_D   = ( 26,  64,  16, 255);  L_M  = ( 40,  94,  26, 255)
    L_L   = ( 58, 122,  36, 255)
    SHORE = ( 92,  76,  44, 255);  SHORL = (122, 104,  64, 255)
    GRASS = ( 74, 124,  38, 255)
    W_D   = ( 16,  84, 154, 255);  W_M  = ( 26, 112, 174, 255)
    W_L   = ( 48, 144, 202, 255);  REFL = (162, 198, 222, 255)

    sky_fill(buf, SKY_T, SKY_B)

    # Tree masses on left and right
    for x in range(18):
        ht = 22 + int(5 * math.sin(x * 0.7 + 0.3))
        for y in range(ht, G):
            if y == ht:
                buf[y, x] = L_L
            elif (x + y) % 5 < 2:
                buf[y, x] = L_D
            else:
                buf[y, x] = L_M

    for x in range(46, G):
        ht = 22 + int(5 * math.sin(x * 0.7 + 1.8))
        for y in range(ht, G):
            if y == ht:
                buf[y, x] = L_L
            elif (x + y) % 5 < 2:
                buf[y, x] = L_D
            else:
                buf[y, x] = L_M

    # Tree trunks
    for tx in [4, 10, 15, 50, 56, 61]:
        for y in range(54, G):
            if 0 <= tx < G:
                buf[y, tx] = TRUNK

    # Water (center column, rows 28-55)
    for y in range(28, 56):
        for x in range(16, 48):
            if y < 32:
                buf[y, x] = W_L
            elif y % 3 == 0 and (x + y // 3) % 5 == 0:
                buf[y, x] = REFL
            elif (x + y * 2) % 9 < 2:
                buf[y, x] = W_D
            else:
                buf[y, x] = W_M

    # Shore fringe
    for x in range(12, 52):
        if 0 <= 55 < G:
            buf[55, x] = GRASS
        for y in range(56, G):
            buf[y, x] = SHORE if (x + y) % 3 else SHORL

    cloud(buf, 21,  8, 11, 3, CLD, CLDS)
    cloud(buf, 25, 10,  6, 2, CLD, CLDS)

    return buf


def gen_swamp() -> np.ndarray:
    buf = canvas()
    SKY_T = ( 82,  92,  62, 255);  SKY_B = (112, 118,  82, 255)
    WAT   = ( 26,  40,  16, 255);  WATL  = ( 40,  56,  26, 255)
    MUD   = ( 62,  48,  26, 255);  MUDD  = ( 42,  32,  14, 255)
    GRASS = ( 52,  74,  26, 255);  GRASL = ( 72, 100,  36, 255)
    REED  = ( 42,  62,  20, 255);  REEDL = ( 62,  86,  30, 255)
    TRUNK = ( 40,  36,  20, 255);  TRKD  = ( 26,  22,  12, 255)
    MOSS  = ( 46,  68,  20, 255)
    SDHED = ( 44,  28,  12, 255)   # cattail seed head
    FOG   = (136, 144, 108, 255)

    sky_fill(buf, SKY_T, SKY_B)

    # Murky water
    for y in range(22, G):
        for x in range(G):
            buf[y, x] = WATL if (x * 3 + y) % 11 < 3 else WAT

    # Mud banks (left, right, center-bottom)
    mud_regions = [
        (0, 30, 15, 9), (0, 48, 20, G - 48),    # left bank
        (50, 34, G - 50, 8), (46, 50, G - 46, G - 50),  # right bank
        (20, 54, 24, G - 54),                     # center mud
    ]
    for bx, by, bw, bh in mud_regions:
        for px in range(bx, min(bx + bw, G)):
            for py in range(by, min(by + bh, G)):
                buf[py, px] = MUD if (px + py) % 3 else MUDD

    # Grass tufts on mud
    for gx, gy in [(2, 29), (7, 29), (4, 47), (11, 47),
                   (51, 33), (57, 33), (54, 49), (48, 49),
                   (24, 53), (34, 53)]:
        if 0 <= gx < G and 0 <= gy < G:
            buf[gy, gx] = GRASL

    # Gnarled trees
    for tx, ty, branches in [
        (5,  20, [(-3, 3), (2, 5), (-2, 7)]),
        (13, 18, [(-2, 4), (3, 6), (-1, 8)]),
        (53, 17, [(-2, 4), (3, 6)]),
        (60, 21, [( 2, 3), (-3, 6)]),
    ]:
        for y in range(ty, min(ty + 16, G)):
            if 0 <= tx < G:
                buf[y, tx] = TRUNK if y % 3 else TRKD
                if y < ty + 4 and tx + 1 < G:
                    buf[y, tx + 1] = TRKD
        for bxo, byo in branches:
            bx, by = tx + bxo, ty + byo
            if 0 <= bx < G and 0 <= by < G:
                buf[by, bx] = TRUNK
                bx2 = min(G - 1, bx + (1 if bxo > 0 else -1))
                buf[by, bx2] = MOSS

    # Reeds / cattails
    for rx in [18, 22, 36, 41, 44]:
        for ry in range(26, 50):
            if 0 <= rx < G and ry < G:
                buf[ry, rx] = REEDL if ry < 34 else REED
        for ry in range(26, 30):
            if ry < G:
                buf[ry, rx] = SDHED

    # Fog wisps at water surface
    for fy in range(22, 26):
        for fx in range(G):
            e = buf[fy, fx].astype(np.float32)
            a = (26 - fy) / 4.0 * 0.55   # stronger fog nearest surface
            buf[fy, fx, 0] = int(e[0] * (1 - a) + FOG[0] * a)
            buf[fy, fx, 1] = int(e[1] * (1 - a) + FOG[1] * a)
            buf[fy, fx, 2] = int(e[2] * (1 - a) + FOG[2] * a)
            buf[fy, fx, 3] = 255

    return buf


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def save(name: str, buf: np.ndarray):
    img = Image.fromarray(buf, 'RGBA').resize((SIZE, SIZE), Image.NEAREST)
    img.save(os.path.join(OUTPUT_DIR, f"bg_{name}.png"), 'PNG')
    print(f"  Saved: bg_{name}.png")


def save_raw(name: str, buf: np.ndarray):
    """Save a texture that is already at full SIZE resolution (no upscale)."""
    Image.fromarray(buf, 'RGBA').save(os.path.join(OUTPUT_DIR, f"bg_{name}.png"), 'PNG')
    print(f"  Saved: bg_{name}.png")


BACKGROUNDS = {
    "grassland": gen_grassland,
    "hills":     gen_hills,
    "mountains": gen_mountains,
    "beach":     gen_beach,
    "ocean":     gen_ocean,
    "lake":      gen_lake,
    "swamp":     gen_swamp,
}

# ---------------------------------------------------------------------------
# Frame-pattern backgrounds — flat rectangles using generate_frames textures
# ---------------------------------------------------------------------------

import importlib.util as _ilu

def _load_gf():
    _spec = _ilu.spec_from_file_location(
        "generate_frames",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "generate_frames.py"),
    )
    _mod = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod


def _build_frame_backgrounds():
    gf = _load_gf()
    bgs = {}
    # Plain colours
    for name, (r, g, b) in gf.PLAIN_COLORS.items():
        bgs[f"plain_{name}"] = lambda r=r, g=g, b=b: gf.gen_solid(r, g, b)
    # Fancy patterns — share names with the frame variants for easy matching
    bgs["Wood_bamboo"]                  = gf.gen_bamboo
    bgs["Wood_dark"]                = gf.gen_darkwoodwithleaves
    bgs["metallic_bronze"]         = gf.gen_metallicbronze
    bgs["metallic_silver"]         = gf.gen_metallicSilver
    bgs["metallic_gold"]           = gf.gen_metallicgold
    bgs["metallic_bronze_corroded"] = gf.gen_metallicbronzecorroded
    bgs["metallic_silver_corroded"] = gf.gen_metallicSilvercorroded
    bgs["metallic_gold_corroded"]   = gf.gen_metallicgoldcorroded
    return bgs


if __name__ == "__main__":

    fbgs  = _build_frame_backgrounds()
    plain = {k: v for k, v in fbgs.items() if k.startswith("plain_")}
    fancy = {k: v for k, v in fbgs.items() if not k.startswith("plain_")}

    print("-- Pixel-art backgrounds ------------------------------------")
    for name, fn in BACKGROUNDS.items():
        save(name, fn())

    print("\n-- Frame-pattern backgrounds (metallic / wood) --------------")
    for name, fn in fancy.items():
        save_raw(name, fn())

    # Plain colours written last → newest mtime → appear at top of input panel
    print("\n-- Plain-colour backgrounds ---------------------------------")
    for name, fn in plain.items():
        save_raw(name, fn())

    total = len(BACKGROUNDS) + len(fbgs)
    print(f"\nDone. {total} backgrounds written to:\n  {OUTPUT_DIR}")
