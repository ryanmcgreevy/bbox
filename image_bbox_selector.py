import json
import os
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk


class ImageBboxSelector:
    def __init__(self, image_path, boxes=None, output_json=None):
        self.root = tk.Tk()
        self.root.title(f"Image BBox Selector - {os.path.basename(image_path)}")

        # Load original image
        self.image_path = image_path
        self.original_image = Image.open(image_path)
        self.original_w, self.original_h = self.original_image.size

        # Display image state
        self.display_image = self.original_image.copy()
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.display_w, self.display_h = self.display_image.size

        # Canvas
        self.canvas = tk.Canvas(self.root, width=self.display_w, height=self.display_h, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw image
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image, tags="image")

        # Bounding boxes are stored in ORIGINAL image coordinates
        # each box: {"x1": int, "y1": int, "x2": int, "y2": int, "label": str}
        self.boxes = [self.validate_box(box) for box in (boxes or [])]

        # During draw operation (in display coords)
        self.current_rect_id = None
        self.start_x = None
        self.start_y = None

        # Legend
        self.legend_visible = True
        self.legend_bg_id = None
        self.legend_text_id = None

        # Output annotation file path is chosen via a Save As dialog
        self.output_json = output_json

        # Bind mouse events
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)

        # Resize handling
        self.canvas.bind("<Configure>", self.on_window_resize)

        # Menu bar
        self.create_menu_bar()

        # Keyboard shortcuts
        self.root.bind("s", self.save_boxes_json_event)     # Save
        self.root.bind("c", self.clear_boxes_event)         # Clear
        self.root.bind("u", self.undo_last_box_event)       # Undo fallback
        self.root.bind("<Control-z>", self.undo_last_box_event)  # Undo
        self.root.bind("l", self.load_boxes_json_event)     # Load JSONL
        self.root.bind("h", self.toggle_legend_event)       # Toggle legend

        # Size the window to the image while keeping it within the display
        self.set_initial_window_size()

        # Initial draw overlays
        self.redraw_overlays()

        self.root.mainloop()

    # -----------------------------
    # Coordinate conversion helpers
    # -----------------------------
    def display_to_original(self, x, y):
        """Convert display/canvas coords to original-image coords."""
        if self.display_w <= 0 or self.display_h <= 0:
            return 0, 0
        scale_x = self.original_w / self.display_w
        scale_y = self.original_h / self.display_h
        ox = int(round(x * scale_x))
        oy = int(round(y * scale_y))
        return ox, oy

    def original_to_display(self, x, y):
        """Convert original-image coords to display/canvas coords."""
        if self.original_w <= 0 or self.original_h <= 0:
            return 0, 0
        scale_x = self.display_w / self.original_w
        scale_y = self.display_h / self.original_h
        dx = int(round(x * scale_x))
        dy = int(round(y * scale_y))
        return dx, dy

    @staticmethod
    def normalize_box(x1, y1, x2, y2):
        return min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)

    def clamp_original(self, x, y):
        x = max(0, min(self.original_w - 1, x))
        y = max(0, min(self.original_h - 1, y))
        return x, y

    @staticmethod
    def validate_box(box):
        return {
            "x1": int(box["x1"]),
            "y1": int(box["y1"]),
            "x2": int(box["x2"]),
            "y2": int(box["y2"]),
            "label": str(box.get("label", ""))
        }

    @staticmethod
    def normalize_image_path(image_path, base_dir=None):
        if not image_path:
            raise ValueError("Annotation record does not contain an image path.")
        if base_dir and not os.path.isabs(image_path):
            image_path = os.path.join(base_dir, image_path)
        return os.path.abspath(image_path)

    def set_initial_window_size(self):
        self.root.update_idletasks()

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        max_w = max(400, screen_w - 100)
        max_h = max(300, screen_h - 120)

        window_w = min(self.display_w, max_w)
        window_h = min(self.display_h, max_h)

        x = max((screen_w - window_w) // 2, 0)
        y = max((screen_h - window_h) // 2, 0)
        self.root.geometry(f"{window_w}x{window_h}+{x}+{y}")

    def create_menu_bar(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Image...", command=self.open_image_event)
        file_menu.add_command(label="Open JSONL...", command=self.load_boxes_json_event)
        file_menu.add_separator()
        file_menu.add_command(label="Save JSONL...", command=self.save_boxes_json_event)
        file_menu.add_separator()
        file_menu.add_command(label="Clear Boxes", command=self.clear_boxes_event)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)

        menubar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menubar)

    # -----------------------------
    # Drawing & events
    # -----------------------------
    def on_button_press(self, event):
        self.start_x, self.start_y = event.x, event.y
        if self.current_rect_id is not None:
            self.canvas.delete(self.current_rect_id)
        self.current_rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2, tags="temp_rect"
        )

    def on_mouse_drag(self, event):
        if self.current_rect_id is not None:
            self.canvas.coords(self.current_rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        if self.start_x is None or self.start_y is None:
            return

        end_x, end_y = event.x, event.y

        # Normalize in display space
        dx1, dy1, dx2, dy2 = self.normalize_box(self.start_x, self.start_y, end_x, end_y)

        # Convert to original-image space
        ox1, oy1 = self.display_to_original(dx1, dy1)
        ox2, oy2 = self.display_to_original(dx2, dy2)

        # Normalize and clamp in original space
        ox1, oy1, ox2, oy2 = self.normalize_box(ox1, oy1, ox2, oy2)
        ox1, oy1 = self.clamp_original(ox1, oy1)
        ox2, oy2 = self.clamp_original(ox2, oy2)

        # Ignore near-zero boxes
        if abs(ox2 - ox1) < 2 or abs(oy2 - oy1) < 2:
            if self.current_rect_id is not None:
                self.canvas.delete(self.current_rect_id)
                self.current_rect_id = None
            return

        # Ask label
        label = simpledialog.askstring("Box Label", "Enter label for this box:", parent=self.root)
        if label is None:
            label = ""  # user cancelled -> empty label

        self.boxes.append({
            "x1": ox1, "y1": oy1, "x2": ox2, "y2": oy2, "label": label
        })

        # Remove temp rectangle and redraw persistent overlays
        if self.current_rect_id is not None:
            self.canvas.delete(self.current_rect_id)
            self.current_rect_id = None

        self.redraw_overlays()
        self.save_boxes_json()  # autosave on each box

    def on_window_resize(self, event):
        # Avoid invalid tiny sizes
        if event.width < 2 or event.height < 2:
            return

        # Resize display image to new canvas size
        self.display_w, self.display_h = event.width, event.height
        self.display_image = self.original_image.resize((self.display_w, self.display_h), Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(self.display_image)

        # Update canvas image
        self.canvas.itemconfig("image", image=self.tk_image)
        self.canvas.coords("image", 0, 0)

        # Redraw boxes/labels/legend
        self.redraw_overlays()

    # -----------------------------
    # Overlay rendering
    # -----------------------------
    def redraw_overlays(self):
        # Remove old overlays (except base image)
        self.canvas.delete("box")
        self.canvas.delete("box_label")
        self.canvas.delete("legend")

        # Draw boxes from original-space data -> display-space
        for i, b in enumerate(self.boxes, start=1):
            dx1, dy1 = self.original_to_display(b["x1"], b["y1"])
            dx2, dy2 = self.original_to_display(b["x2"], b["y2"])

            self.canvas.create_rectangle(
                dx1, dy1, dx2, dy2,
                outline="red", width=2, tags="box"
            )

            # Label text shown near top-left of box
            label_text = b["label"] if b["label"] else f"box_{i}"
            self.canvas.create_text(
                dx1 + 4, max(10, dy1 - 8),
                text=label_text,
                fill="red",
                anchor="w",
                font=("Arial", 14, "bold"),
                tags="box_label"
            )

        if self.legend_visible:
            self.draw_legend()

    def draw_legend(self):
        legend_text = (
            "Shortcuts: S=Save  L=Load  C=Clear  Ctrl+Z/U=Undo  H=Hide/Show\n"
            f"Boxes: {len(self.boxes)}"
        )

        # Place at top-left
        x, y = 10, 10
        text_id = self.canvas.create_text(
            x, y,
            text=legend_text,
            fill="white",
            anchor="nw",
            font=("Arial", 10),
            tags="legend"
        )
        bbox = self.canvas.bbox(text_id)
        if bbox:
            x1, y1, x2, y2 = bbox
            pad = 6
            bg_id = self.canvas.create_rectangle(
                x1 - pad, y1 - pad, x2 + pad, y2 + pad,
                fill="#000000", outline="#666666", width=1,
                tags="legend"
            )
            # Raise text above background
            self.canvas.tag_raise(text_id, bg_id)

    # -----------------------------
    # Actions
    # -----------------------------
    @staticmethod
    def load_annotation_records(annotation_path):
        records = []
        with open(annotation_path, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Invalid JSON Lines record on line {line_number}: {exc}") from exc
                if not isinstance(record, dict):
                    raise ValueError(f"Annotation record on line {line_number} must be a JSON object.")
                records.append(record)

        if not records:
            raise ValueError("Annotation file does not contain any JSON Lines records.")
        return records

    @classmethod
    def read_annotation_file(cls, annotation_path, parent=None):
        records = cls.load_annotation_records(annotation_path)

        if len(records) == 1:
            record = records[0]
        else:
            prompt_lines = [
                "This JSON Lines file contains multiple image records.",
                "Enter the record number to load:",
                ""
            ]
            for index, record in enumerate(records, start=1):
                image_name = os.path.basename(str(record.get("image", f"record_{index}")))
                box_count = len(record.get("boxes", []))
                prompt_lines.append(f"{index}: {image_name} ({box_count} boxes)")

            selected_index = simpledialog.askinteger(
                "Select Record",
                "\n".join(prompt_lines[:25]),
                minvalue=1,
                maxvalue=len(records),
                parent=parent
            )
            if selected_index is None:
                raise ValueError("Annotation load cancelled.")
            record = records[selected_index - 1]

        image_path = cls.normalize_image_path(record.get("image"), os.path.dirname(annotation_path))
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        boxes = [cls.validate_box(box) for box in record.get("boxes", [])]
        return image_path, boxes

    def build_annotation_record(self):
        return {
            "image": os.path.abspath(self.image_path),
            "image_size": {"width": self.original_w, "height": self.original_h},
            "boxes": self.boxes
        }

    def get_default_output_path(self):
        image_dir = os.path.dirname(self.image_path) or "."
        image_name = os.path.splitext(os.path.basename(self.image_path))[0]
        return os.path.join(image_dir, f"{image_name}_bounding_boxes.jsonl")

    def choose_output_json_path(self):
        initial_path = self.output_json or self.get_default_output_path()
        selected_path = filedialog.asksaveasfilename(
            title="Save bounding boxes JSON Lines",
            defaultextension=".jsonl",
            initialdir=os.path.dirname(initial_path) or ".",
            initialfile=os.path.basename(initial_path),
            filetypes=[("JSON Lines files", "*.jsonl"), ("All files", "*.*")]
        )
        if selected_path:
            self.output_json = selected_path
            return True
        return False

    def load_boxes_json(self, json_path=None):
        if not json_path:
            json_path = filedialog.askopenfilename(
                title="Open bounding boxes JSON Lines",
                filetypes=[("JSON Lines files", "*.jsonl"), ("All files", "*.*")]
            )
            if not json_path:
                return False

        image_path, boxes = self.read_annotation_file(json_path, parent=self.root)

        self.image_path = image_path
        self.original_image = Image.open(image_path)
        self.original_w, self.original_h = self.original_image.size
        self.display_image = self.original_image.copy()
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.display_w, self.display_h = self.display_image.size

        self.canvas.config(width=self.display_w, height=self.display_h)
        self.canvas.itemconfig("image", image=self.tk_image)
        self.canvas.coords("image", 0, 0)

        self.boxes = boxes
        self.output_json = json_path
        self.root.title(f"Image BBox Selector - {os.path.basename(image_path)}")

        self.set_initial_window_size()
        self.redraw_overlays()
        return True

    def load_boxes_json_event(self, _event=None):
        try:
            if self.load_boxes_json():
                messagebox.showinfo("Loaded", f"Loaded {len(self.boxes)} boxes from {self.output_json}")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def open_image_event(self):
        image_path = filedialog.askopenfilename(
            title="Open image",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"), ("All files", "*.*")]
        )
        if not image_path:
            return

        self.image_path = image_path
        self.original_image = Image.open(image_path)
        self.original_w, self.original_h = self.original_image.size
        self.display_image = self.original_image.copy()
        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.display_w, self.display_h = self.display_image.size

        self.canvas.config(width=self.display_w, height=self.display_h)
        self.canvas.itemconfig("image", image=self.tk_image)
        self.canvas.coords("image", 0, 0)

        self.boxes = []
        self.output_json = None
        self.root.title(f"Image BBox Selector - {os.path.basename(image_path)}")

        self.set_initial_window_size()
        self.redraw_overlays()

    def save_boxes_json(self, prompt_for_path=False):
        if prompt_for_path or not self.output_json:
            if not self.choose_output_json_path():
                print("Save cancelled.")
                return False

        records = []
        if os.path.exists(self.output_json) and os.path.getsize(self.output_json) > 0:
            try:
                records = self.load_annotation_records(self.output_json)
            except ValueError as exc:
                messagebox.showerror("Save Error", f"Could not update annotation file:\n{exc}")
                return False

        data = self.build_annotation_record()
        current_image_path = os.path.abspath(self.image_path)
        updated = False

        for index, record in enumerate(records):
            try:
                existing_image_path = self.normalize_image_path(record.get("image"), os.path.dirname(self.output_json))
            except (TypeError, ValueError):
                continue

            if existing_image_path == current_image_path:
                records[index] = data
                updated = True
                break

        if not updated:
            records.append(data)

        with open(self.output_json, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")

        print(f"Saved {len(self.boxes)} boxes for {os.path.basename(self.image_path)} to {self.output_json}")
        return True

    def save_boxes_json_event(self, _event=None):
        if self.save_boxes_json(prompt_for_path=True):
            messagebox.showinfo("Saved", f"Saved {len(self.boxes)} boxes to {self.output_json}")

    def clear_boxes_event(self, _event=None):
        if not self.boxes:
            return
        confirm = messagebox.askyesno("Clear Boxes", "Clear all bounding boxes?")
        if confirm:
            self.boxes.clear()
            self.redraw_overlays()
            self.save_boxes_json()

    def undo_last_box_event(self, _event=None):
        if self.boxes:
            self.boxes.pop()
            self.redraw_overlays()
            self.save_boxes_json()

    def toggle_legend_event(self, _event=None):
        self.legend_visible = not self.legend_visible
        self.redraw_overlays()


if __name__ == "__main__":
    # Hide root during file picker to avoid odd UX flash
    picker_root = tk.Tk()
    picker_root.withdraw()
    selected_path = filedialog.askopenfilename(
        title="Select image or annotation file",
        filetypes=[
            ("Supported files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.jsonl"),
            ("JSON Lines files", "*.jsonl"),
            ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"),
            ("All files", "*.*")
        ]
    )
    if selected_path:
        if selected_path.lower().endswith(".jsonl"):
            image_path, boxes = ImageBboxSelector.read_annotation_file(selected_path, parent=picker_root)
            picker_root.destroy()
            ImageBboxSelector(image_path, boxes=boxes, output_json=selected_path)
        else:
            picker_root.destroy()
            ImageBboxSelector(selected_path)
    else:
        picker_root.destroy()