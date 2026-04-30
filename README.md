# RPG Token Generator

A standalone desktop tool for compositing character tokens for virtual tabletops (Roll20, Foundry VTT, etc.). No internet connection or Python installation required.

## Download

Go to the [Releases](../../releases) page and download the latest `RPG-Token-Generator-vX.X.X.zip`. Unzip it anywhere and run `RPG Token Generator.exe`.

## Folder Structure

```
RPG Token Generator.exe
Backgrounds/    ← drop your own background images here
Figures/        ← drop your own character/creature PNGs here
Frames/         ← drop your own frame overlays here
Tokens/         ← exported tokens are saved here
```

PNG, WebP, JPEG, and SVG files are supported. The app scans each folder on launch, so just add files and restart to see them.

## Making a Token

**1. Pick a frame.** Click a frame in the right column of the Inputs panel. The frame defines the crop boundary for the exported token.

**2. Add a figure.** Click a character image in the center column. Drag, rotate, and resize it on the canvas using the handles that appear when you click it. Right-click for precise layer and position controls.

**3. Add a background (optional).** Click a background image in the left column. Backgrounds sit behind figures by default.

**4. Export.** Click the green Print button in the Output panel. The token is saved to the `Tokens/` folder, named after the active figure. You can rename it before saving.

## Canvas Controls

Left-click an item to select it and reveal transform handles. Drag the center to move, drag edges to scale, drag corners to scale while preserving aspect ratio, and drag the circular handle at the top to rotate. Right-click any item for a context menu with layer ordering, numeric position/scale/rotation inputs, and a remove option.

## Session Memory

Every exported token is listed in the Session Memory section of the Output panel. Clicking an entry restores the full workspace state so you can make adjustments and re-export.

## Running from Source

```bash
pip install PyQt6 Pillow numpy
python "Token Generator/main.py"
```

To regenerate the bundled frames and backgrounds:

```bash
python generate_frames.py
python generate_backgrounds.py
```

## Building the Executable

```bash
pip install pyinstaller
build.bat
```

The assembled release folder appears at `dist\release\`.
