# RPG Token Generator

A standalone desktop tool for composing character tokens for virtual tabletops such as Roll20 or Foundry. The executable is open source python code, but you don't need python to download the app and run it.

## Download

Go to the [Releases](../../releases) page and download the latest `RPG-Token-Generator-vX.X.X.zip`. You can unzip it anywhere and run `RPG Token Generator.exe`.

## Folder Structure

```
RPG Token Generator.exe
Backgrounds/    ← drop your own background images here
Figures/        ← drop your own character/creature PNGs here
Frames/         ← drop your own frame overlays here
Tokens/         ← exported tokens are saved here
```

PNG, WebP, JPEG, and SVG files are supported. Each folder is rescanned every 2 seconds, so files dropped in while the app is running will appear automatically.

## Making a Token

**1. Pick a frame.** Click a frame in the right column of the Inputs panel. You can adjust it in the options bar at the bottom. The frame defines the orientation and crop boundary for the exported token, so you can only have one at a time.

**2. Add a figure.** Click a character image in the center column. You can adjust by left clicking and selecting a handle, or by right clicking for precise layer and position controls. You may have multiple at once.

**3. Add a background (optional).** Click a background image in the left column. Backgrounds sit behind figures by default. You may have multiple at once.

Items can be deactivated by clicking them again.

**4. Export.** Click the green Print button in the Output panel. The token is saved to the `Tokens/` folder, named after the active figure. You can rename it before saving.

## Session Memory

Every exported token is listed in the Session Memory section of the Output panel. Clicking an entry restores the full workspace state so you can make adjustments and re-export.

## Running from Source

```bash
pip install PyQt6 Pillow numpy
python main.py
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

## Art

Level2Janitor provided the sample figures. See https://level2janitor.itch.io/ for more of his work.
