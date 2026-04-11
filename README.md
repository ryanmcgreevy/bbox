# bbox

Simple Python tool for drawing **labeled bounding boxes** on images and saving/loading them as **JSON Lines (`.jsonl`)** annotation files.

## Features

- Open an image and draw bounding boxes with the mouse
- Add a text label to each box
- Save annotations to a `.jsonl` file
- Reopen a `.jsonl` file and display its saved boxes and labels
- Store **one record per image**, with all boxes and tags for that image on a single line
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
2. Open an image or an existing annotation `.jsonl` file.
3. Click and drag on the image to create a bounding box.
4. Enter a label when prompted.
5. Save the annotations to a `.jsonl` file.

## Shortcuts

- `S` — save JSONL
- `L` — load JSONL
- `C` — clear all boxes
- `Ctrl+Z` or `U` — undo last box
- `H` — hide/show legend

## JSON Lines format

Annotations are stored in **JSON Lines** format. Each line is one JSON object for a single image, including all bounding boxes and labels for that image.

Example `.jsonl` record:

```json
{"image":"example.jpg","image_size":{"width":1920,"height":1080},"boxes":[{"x1":100,"y1":120,"x2":400,"y2":500,"label":"deer"}]}
```

### Notes

- **One line = one image annotation record**
- A single record contains **all** boxes for that image
- The app can still read older `.json` annotation files for compatibility
