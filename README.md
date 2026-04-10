# bbox

Simple Python tool for drawing **labeled bounding boxes** on images and saving/loading them as JSON.

## Features

- Open an image and draw bounding boxes with the mouse
- Add a text label to each box
- Save annotations to a JSON file
- Reopen a JSON file and display its saved boxes and labels
- Use keyboard shortcuts or the menu bar for common actions

## Requirements

- Python 3
- `Pillow`
- `tkinter` (usually included with Python)

## Install

```bash
pip install pillow
```

## Run

```bash
python image_bbox_selector.py
```

## Basic usage

1. Launch the app.
2. Open an image or an existing annotation JSON file.
3. Click and drag on the image to create a bounding box.
4. Enter a label when prompted.
5. Save the annotations to a `.json` file.

## Shortcuts

- `S` — save JSON
- `L` — load JSON
- `C` — clear all boxes
- `Ctrl+Z` or `U` — undo last box
- `H` — hide/show legend

## JSON format

Example output:

```json
{
  "image": "example.jpg",
  "image_size": {
    "width": 1920,
    "height": 1080
  },
  "boxes": [
    {
      "x1": 100,
      "y1": 120,
      "x2": 400,
      "y2": 500,
      "label": "deer"
    }
  ]
}
```
