# Portrait to G-code

A camera-to-plotter workflow for turning portrait photos into pen-plotter-ready G-code.

The project is built around three parts:

- `manager.py` opens the camera UI, captures named portraits, and runs background jobs.
- `img2gpt/` converts a portrait into clean coloring-book style line art using the OpenAI Image API.
- `img2gcode/` traces the line-art image and generates drawable G-code for the CNC / pen plotter.

## Credits

The G-code tracing part is based on the original work by [schollz](https://github.com/schollz). If this project helps you, please also check out and star the original repository: [schollz/img2gcode](https://github.com/schollz/img2gcode).

This fork adapts that idea for a custom ZedBoard / FPGA-controlled pen plotter workflow.

## Workflow

1. Open the manager UI.
2. Enter a person's name.
3. Take a photo with the laptop / PC camera.
4. The raw photo is saved in `source images/`.
5. GPT converts the photo into coloring-book style line art.
6. `img2gcode` converts that line-art image into G-code.
7. The final plotter-ready file appears in `gcode outputs/`.

The manager runs jobs in the background, so the camera UI stays usable while GPT and G-code conversion are running.

## Folder Structure

```text
manager.py                 Main camera UI and job manager
source images/             Raw captured photos and manual source images
gcode outputs/             Final plotter-ready .gcode files only

img2gpt/
  img2gpt.py               OpenAI image conversion script
  prompts/                 Prompt text used for image conversion
  history/                 Generated coloring-book images

img2gcode/
  img2gcode.py             Image tracing and G-code generation script
  history/                 Intermediate trace artifacts per run
  .tools/                  Bundled helper tools, including potrace
```

## Setup

Create or activate a Python virtual environment, then install the Python packages:

```powershell
python -m pip install openai opencv-python pillow click loguru numpy simplification svgpathtools svgwrite tqdm svg.path
```

The OpenAI API key can be provided either as an environment variable:

```powershell
$env:OPENAI_API_KEY="your_api_key_here"
```

or in this ignored local file:

```text
img2gpt/GPT_API_Key.txt
```

## Run the Manager

From the repo root:

```powershell
.venv\Scripts\python.exe manager.py
```

In Git Bash:

```bash
./.venv/Scripts/python.exe manager.py
```

If the virtual environment is already active:

```bash
python manager.py
```

## Current Defaults

GPT image conversion:

- model: `gpt-image-2`
- quality: `medium`
- size: `1024x1536`

G-code generation:

- drawing area: `190 x 190 mm`
- pen down: `Z0`
- pen up: `Z5`
- XY feed rate: `F5400`
- pen movement feed rate: `F500`
- output orientation corrected to match the source image

## Direct Script Usage

Run GPT conversion manually:

```powershell
python img2gpt\img2gpt.py --input "source images\test.png"
```

Run G-code conversion manually:

```powershell
python img2gcode\img2gcode.py --file "img2gpt\history\test_coloring.png" --threshold 80 --no-minimize
```

## License

MIT. The original MIT license notice from `schollz/img2gcode` is preserved in `LICENSE`.
