# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project Overview

This is a **standalone RPG token generator** for virtual tabletops (Roll20, Foundry VTT, etc.). It runs entirely offline on the user's machine. No code has been written yet — this repo contains the specification (`Product Goal.txt`) and example output tokens in `Example Tokens/`.

The final deliverable lives in the `Token Generator/` subdirectory. All work files, experiments, and collected assets go in the parent `Claude-Token Generator/` directory. **Never edit anything outside the `Claude-Token Generator/` parent folder.**

## Planned File Structure (inside `Token Generator/`)

```
Token Generator/
├── Backgrounds/    # PNG/WebP background images (input)
├── Figures/        # PNG/WebP character/creature cutouts (input)
├── Frames/         # PNG/WebP token frames (input)
└── Tokens/         # Exported token output
```

## Architecture

The app is a single GUI program with three panels:

**Left — Inputs**: Three columns (Backgrounds, Figures, Frames) showing images newest-to-oldest. Images glow on hover; dimly glow when selected. Max 8 figures + 8 backgrounds + 1 frame active at a time. Red "Clear" button deselects everything.

**Center — Workspace**: Canvas with grey/white grid (transparent on export). Supports up to 8 figures + 8 backgrounds + 1 frame simultaneously. Left-click to move/stretch/rotate; right-click for a property menu (layer, position, stretch, rotation, deselect). Layer system: backgrounds spawn at -5, figures at 0, frame at +5. Layers are arbitrary integers.

**Right — Outputs**:
- **Preview**: 400×400px live capture cropped tightly around the selected frame, with transparency outside the frame boundary. Shows a blue box (or animated grey gears) when no frame is selected.
- **Print button** (green): Exports a PNG matching the preview to `Tokens/`, name defaulting to the most-recently-selected figure filename (user can override). Also saves an in-memory workspace snapshot.
- **Session Memory**: Scrollable list of printed tokens from the current session. Clicking one restores that workspace state.

## Token Anatomy

- **Background**: Full portrait/landscape layer; spawns at layer -5.
- **Figure**: Character/creature with transparent background; spawns at layer 0.
- **Frame**: Decorative border (circular, hexagonal, decorated) with transparency inside, outside, and sometimes internally; spawns at layer +5. The frame defines the output crop boundary.

## Bonus Features (noted in spec)

- Image name filtering in input columns.
- Animated gear placeholder (retracts when frame selected, returns when deselected/cleared).
- Integrated trimming tool in a separate GUI window: lets users paint transparency onto figures/frames and save back to the input folder.

## Technology Stack

- **GUI**: PyQt6 — required for this project's complexity (custom canvas, drag/rotate/scale handles, layered compositing, animated elements, right-click context menus). tkinter lacks the necessary widget richness.
- **Image compositing**: Pillow (PIL) — handles PNG/WebP, alpha blending, rotation, and export.
- **Packaging**: PyInstaller — produces a standalone `.exe` with no Python install required.

## Commands

```bash
# Install dependencies
pip install PyQt6 Pillow pyinstaller

# Run the app (once implemented)
python Token\ Generator/main.py

# Build standalone executable
pyinstaller --onefile --windowed Token\ Generator/main.py
```
