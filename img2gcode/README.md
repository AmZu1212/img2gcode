# img2gcode

Thanks to [schollz](https://github.com/schollz) for the original project. If this tool helps you, please star the original repo here: [schollz/img2gcode](https://github.com/schollz/img2gcode).

This repository is a fork of the original work, adapted for a custom pen plotter.

## What it does

`img2gcode.py` converts black-and-white line art into:

- `image.gcode` for a pen plotter
- `final.svg` for vector preview
- `final.png` for raster preview

This fork outputs G-code in a pen-plotter style:

- `Z0` = pen touching paper
- `Z5` = pen lifted for travel
- `F5400` on XY movement lines (Feed rate is used to set the plotter's movement speed)
- `F500` on pen up/down moves
- output automatically fit inside a `190 x 190 mm` drawing area

## Requirements

This fork is currently set up and tested for Windows.

You need:

- Python 3
- ImageMagick
- `potrace`

Python packages:

```powershell
python -m pip install click loguru numpy simplification svgpathtools svgwrite tqdm pillow svg.path
```

## Usage

Basic run:

```powershell
python img2gcode\img2gcode.py --file "source images\your_image.png" --threshold 80 --no-minimize
```

Each run creates a timestamped output folder inside `img2gcode/history/`, for example:

```text
img2gcode/history/girl_smiling_test_18-16_on_2026-06-24
```

It also writes a plotter-ready copy into `gcode outputs/`:

```text
gcode outputs/girl_smiling_test_18-16_on_2026-06-24.gcode
```

Inside that folder:

- `image.gcode` is the final plotter output
- `final.svg` is the vector preview
- `final.png` is the rendered preview
- `thresholded.png` shows the thresholded source image
- `potrace.svg` shows the traced intermediate result

## Useful options

- `--threshold 80`
  Controls black/white separation during tracing.

- `--simplify 0.25`
  Reduces point count while keeping shape quality.

- `--min-segment-length 0.2`
  Removes tiny segments that bloat the G-code.

- `--bezier-segments 12`
  Controls curve sampling detail.

- `--no-minimize`
  Skips path travel optimization.

- `--minx 0 --maxx 190 --miny 0 --maxy 190`
  Drawing bed limits. Default is already `190 x 190`.

## Example

```powershell
python img2gcode\img2gcode.py --file "source images\girl smiling test.png" --threshold 80 --no-minimize
```

## License

MIT
