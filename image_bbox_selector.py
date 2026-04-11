import json
import os
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox
from PIL import Image, ImageTk


class ImageBboxSelector:
    SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff")

    def __init__(
        self,
        image_path=None,
        boxes=None,
        output_json=None,
        image_records=None,
        selected_image_path=None,
        image_paths=None,
    ):
        self.root = tk.Tk()
        self.root.title("Image BBox Selector")

        # Loaded image records keyed by absolute image path
        self.loaded_images = {}
        self.loaded_image_order = []
        self.current_image_path = None
        self._updating_image_list = False

        # Current display state
        self.image_path = None
        self.original_image = None
        self.original_w = 1
        self.original_h = 1
        self.display_image = None
        self.tk_image = None
        self.display_w = 800
        self.display_h = 600

        # Bounding boxes are stored in ORIGINAL image coordinates
        self.boxes = []

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

        # Main layout
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.sidebar_frame = tk.Frame(self.main_frame, width=240)
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        self.sidebar_frame.pack_propagate(False)

        self.image_list_label = tk.Label(
            self.sidebar_frame,
            text="Loaded Images",
            anchor="w",
            font=("Arial", 10, "bold")
        )
        self.image_list_label.pack(fill=tk.X, pady=(0, 4))

        self.image_listbox = tk.Listbox(self.sidebar_frame, exportselection=False)
        self.image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.image_listbox.bind("<<ListboxSelect>>", self.on_image_list_select)

        self.image_list_scrollbar = tk.Scrollbar(self.sidebar_frame, orient=tk.VERTICAL, command=self.image_listbox.yview)
        self.image_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.image_listbox.config(yscrollcommand=self.image_list_scrollbar.set)

        self.canvas_frame = tk.Frame(self.main_frame)
        self.canvas_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Canvas
        self.canvas = tk.Canvas(self.canvas_frame, width=self.display_w, height=self.display_h, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Draw image container
        self.canvas.create_image(0, 0, anchor=tk.NW, tags="image")

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

        if image_records:
            self.set_loaded_records(
                image_records,
                selected_image_path=selected_image_path or image_path,
                output_json=output_json,
                prompt_selection=selected_image_path is None and len(image_records) > 1,
            )
        elif image_paths:
            self.set_loaded_image_paths(
                image_paths,
                output_json=output_json,
                prompt_selection=len(image_paths) > 1,
            )
        elif image_path:
            initial_record = self.create_image_record(image_path, boxes=boxes or [])
            self.set_loaded_records(
                [initial_record],
                selected_image_path=initial_record["image"],
                output_json=output_json,
                prompt_selection=False,
            )
        else:
            raise ValueError("An image path or annotation records are required to start the selector.")

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

    @classmethod
    def is_supported_image_path(cls, image_path):
        return str(image_path).lower().endswith(cls.SUPPORTED_IMAGE_EXTENSIONS)

    def create_image_record(self, image_path, boxes=None):
        image_path = os.path.abspath(image_path)
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        with Image.open(image_path) as image:
            width, height = image.size

        return {
            "image": image_path,
            "image_size": {"width": width, "height": height},
            "boxes": [self.validate_box(box) for box in (boxes or [])]
        }

    @staticmethod
    def prompt_for_image_selection(image_paths, parent=None, prompt_title="Select Image", intro_text="Multiple images are loaded."):
        if not image_paths:
            return None
        if len(image_paths) == 1:
            return image_paths[0]

        prompt_lines = [intro_text, "Enter the number to display:", ""]
        for index, image_path in enumerate(image_paths, start=1):
            prompt_lines.append(f"{index}: {os.path.basename(image_path)}")

        selected_index = simpledialog.askinteger(
            prompt_title,
            "\n".join(prompt_lines[:30]),
            minvalue=1,
            maxvalue=len(image_paths),
            parent=parent
        )
        if selected_index is None:
            return image_paths[0]
        return image_paths[selected_index - 1]

    def sync_current_image_record(self):
        if self.current_image_path and self.current_image_path in self.loaded_images:
            self.loaded_images[self.current_image_path]["boxes"] = [self.validate_box(box) for box in self.boxes]
            self.loaded_images[self.current_image_path]["image_size"] = {
                "width": int(self.original_w),
                "height": int(self.original_h)
            }

    def set_loaded_records(self, image_records, selected_image_path=None, output_json=None, prompt_selection=False):
        normalized_records = []

        for record in image_records:
            image_path = self.normalize_image_path(record.get("image"))
            normalized_record = self.create_image_record(image_path, boxes=record.get("boxes", []))

            image_size = record.get("image_size") or {}
            if "width" in image_size and "height" in image_size:
                normalized_record["image_size"] = {
                    "width": int(image_size["width"]),
                    "height": int(image_size["height"])
                }

            replaced = False
            for index, existing_record in enumerate(normalized_records):
                if existing_record["image"] == image_path:
                    normalized_records[index] = normalized_record
                    replaced = True
                    break

            if not replaced:
                normalized_records.append(normalized_record)

        if not normalized_records:
            raise ValueError("No images were loaded.")

        self.loaded_images = {record["image"]: record for record in normalized_records}
        self.loaded_image_order = [record["image"] for record in normalized_records]
        self.output_json = output_json

        if selected_image_path:
            selected_image_path = os.path.abspath(selected_image_path)

        if selected_image_path not in self.loaded_images:
            if prompt_selection and len(self.loaded_image_order) > 1:
                selected_image_path = self.prompt_for_image_selection(
                    self.loaded_image_order,
                    parent=self.root,
                    prompt_title="Select Image",
                    intro_text="Multiple images are loaded."
                )
            else:
                selected_image_path = self.loaded_image_order[0]

        self.display_image_path(selected_image_path)

    def set_loaded_image_paths(self, image_paths, output_json=None, prompt_selection=False):
        unique_paths = []
        for image_path in image_paths:
            image_path = os.path.abspath(image_path)
            if self.is_supported_image_path(image_path) and image_path not in unique_paths:
                unique_paths.append(image_path)

        if not unique_paths:
            raise ValueError("No supported image files were selected.")

        selected_image_path = unique_paths[0]
        if prompt_selection and len(unique_paths) > 1:
            selected_image_path = self.prompt_for_image_selection(
                unique_paths,
                parent=self.root,
                prompt_title="Select Image",
                intro_text="Multiple images are loaded."
            )

        image_records = [self.create_image_record(image_path) for image_path in unique_paths]
        self.set_loaded_records(
            image_records,
            selected_image_path=selected_image_path,
            output_json=output_json,
            prompt_selection=False
        )

    def refresh_image_list(self, select_path=None):
        self._updating_image_list = True
        self.image_listbox.delete(0, tk.END)

        for image_path in self.loaded_image_order:
            box_count = len(self.loaded_images[image_path].get("boxes", []))
            self.image_listbox.insert(tk.END, f"{os.path.basename(image_path)} ({box_count})")

        target_path = select_path or self.current_image_path
        if target_path in self.loaded_image_order:
            index = self.loaded_image_order.index(target_path)
            self.image_listbox.selection_clear(0, tk.END)
            self.image_listbox.selection_set(index)
            self.image_listbox.see(index)

        self._updating_image_list = False

    def on_image_list_select(self, _event=None):
        if self._updating_image_list:
            return

        selection = self.image_listbox.curselection()
        if not selection:
            return

        image_path = self.loaded_image_order[selection[0]]
        if image_path != self.current_image_path:
            self.display_image_path(image_path)

    def display_image_path(self, image_path):
        image_path = os.path.abspath(image_path)
        if image_path not in self.loaded_images:
            raise ValueError(f"Image is not loaded: {image_path}")

        self.sync_current_image_record()

        with Image.open(image_path) as image:
            self.original_image = image.copy()

        self.current_image_path = image_path
        self.image_path = image_path
        self.original_w, self.original_h = self.original_image.size
        self.current_rect_id = None
        self.start_x = None
        self.start_y = None

        self.boxes = [self.validate_box(box) for box in self.loaded_images[image_path].get("boxes", [])]
        self.root.title(f"Image BBox Selector - {os.path.basename(image_path)}")

        self.refresh_image_list(select_path=image_path)
        self.set_initial_window_size()
        self.root.update_idletasks()
        self.update_canvas_image()
        self.redraw_overlays()

    def update_canvas_image(self, available_width=None, available_height=None):
        if self.original_image is None:
            return

        if available_width is None:
            available_width = self.canvas.winfo_width()
        if available_height is None:
            available_height = self.canvas.winfo_height()

        available_width = max(1, int(available_width))
        available_height = max(1, int(available_height))

        scale = min(
            available_width / max(1, self.original_w),
            available_height / max(1, self.original_h),
            1.0,
        )

        self.display_w = max(1, int(round(self.original_w * scale)))
        self.display_h = max(1, int(round(self.original_h * scale)))

        if (self.display_w, self.display_h) == (self.original_w, self.original_h):
            self.display_image = self.original_image.copy()
        else:
            self.display_image = self.original_image.resize((self.display_w, self.display_h), Image.Resampling.LANCZOS)

        self.tk_image = ImageTk.PhotoImage(self.display_image)
        self.canvas.itemconfig("image", image=self.tk_image)
        self.canvas.coords("image", 0, 0)

    def is_window_fullscreen(self):
        try:
            if bool(self.root.attributes("-fullscreen")):
                return True
        except tk.TclError:
            pass

        try:
            return self.root.state() == "zoomed"
        except tk.TclError:
            return False

    def set_initial_window_size(self):
        self.root.update_idletasks()

        if self.is_window_fullscreen():
            return

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        sidebar_w = max(220, self.sidebar_frame.winfo_reqwidth())
        canvas_extra_w = max(16, self.canvas_frame.winfo_reqwidth() - self.canvas.winfo_reqwidth())
        canvas_extra_h = max(16, self.canvas_frame.winfo_reqheight() - self.canvas.winfo_reqheight())
        window_extra_w = max(16, self.root.winfo_reqwidth() - self.main_frame.winfo_reqwidth())
        window_extra_h = max(16, self.root.winfo_reqheight() - self.main_frame.winfo_reqheight())

        max_canvas_w = max(400, screen_w - sidebar_w - canvas_extra_w - window_extra_w - 40)
        max_canvas_h = max(300, screen_h - canvas_extra_h - window_extra_h - 60)

        scale = min(
            max_canvas_w / max(1, self.original_w),
            max_canvas_h / max(1, self.original_h),
            1.0,
        )
        target_canvas_w = max(1, int(round(self.original_w * scale)))
        target_canvas_h = max(1, int(round(self.original_h * scale)))

        self.canvas.config(width=target_canvas_w, height=target_canvas_h)

        window_w = min(target_canvas_w + sidebar_w + canvas_extra_w + window_extra_w + 16, screen_w - 20)
        window_h = min(target_canvas_h + canvas_extra_h + window_extra_h + 16, screen_h - 40)

        x = max((screen_w - int(window_w)) // 2, 0)
        y = max((screen_h - int(window_h)) // 2, 0)
        self.root.geometry(f"{int(window_w)}x{int(window_h)}+{x}+{y}")

    def create_menu_bar(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Image(s)...", command=self.open_image_event)
        file_menu.add_command(label="Open Folder...", command=self.open_folder_event)
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

        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.redraw_overlays()
        self.save_boxes_json()  # autosave on each box

    def on_window_resize(self, event):
        if event.widget is not self.canvas or self.original_image is None:
            return

        # Avoid invalid tiny sizes
        if event.width < 2 or event.height < 2:
            return

        self.update_canvas_image(event.width, event.height)

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
        current_index = 0
        if self.current_image_path in self.loaded_image_order:
            current_index = self.loaded_image_order.index(self.current_image_path) + 1

        legend_text = (
            "Shortcuts: S=Save  L=Load  C=Clear  Ctrl+Z/U=Undo  H=Hide/Show\n"
            f"Image: {current_index}/{len(self.loaded_image_order)}  Boxes: {len(self.boxes)}"
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
        raw_records = cls.load_annotation_records(annotation_path)
        image_records = []
        image_paths = []

        for record in raw_records:
            image_path = cls.normalize_image_path(record.get("image"), os.path.dirname(annotation_path))
            if not os.path.exists(image_path):
                raise FileNotFoundError(f"Image not found: {image_path}")

            with Image.open(image_path) as image:
                width, height = image.size

            image_records.append({
                "image": image_path,
                "image_size": {"width": width, "height": height},
                "boxes": [cls.validate_box(box) for box in record.get("boxes", [])]
            })
            image_paths.append(image_path)

        selected_image_path = cls.prompt_for_image_selection(
            image_paths,
            parent=parent,
            prompt_title="Select Image",
            intro_text="This JSON Lines file contains multiple image records."
        )
        return image_records, selected_image_path

    def build_annotation_record(self, image_path=None):
        self.sync_current_image_record()

        image_path = os.path.abspath(image_path or self.current_image_path)
        record = self.loaded_images[image_path]
        image_size = record.get("image_size", {})

        return {
            "image": image_path,
            "image_size": {
                "width": int(image_size.get("width", self.original_w)),
                "height": int(image_size.get("height", self.original_h))
            },
            "boxes": [self.validate_box(box) for box in record.get("boxes", [])]
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

        image_records, selected_image_path = self.read_annotation_file(json_path, parent=self.root)
        self.set_loaded_records(
            image_records,
            selected_image_path=selected_image_path,
            output_json=json_path,
            prompt_selection=False
        )
        return True

    def load_boxes_json_event(self, _event=None):
        try:
            if self.load_boxes_json():
                messagebox.showinfo("Loaded", f"Loaded {len(self.loaded_image_order)} image(s) from {self.output_json}")
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def open_image_event(self):
        image_paths = filedialog.askopenfilenames(
            title="Open image files",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"), ("All files", "*.*")]
        )
        if not image_paths:
            return

        try:
            self.set_loaded_image_paths(image_paths, output_json=None, prompt_selection=len(image_paths) > 1)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def open_folder_event(self):
        folder_path = filedialog.askdirectory(title="Open folder of images")
        if not folder_path:
            return

        image_paths = [
            os.path.join(folder_path, name)
            for name in sorted(os.listdir(folder_path))
            if self.is_supported_image_path(name)
        ]

        if not image_paths:
            messagebox.showinfo("No Images Found", "No supported image files were found in the selected folder.")
            return

        try:
            self.set_loaded_image_paths(image_paths, output_json=None, prompt_selection=len(image_paths) > 1)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def save_boxes_json(self, prompt_for_path=False):
        if prompt_for_path or not self.output_json:
            if not self.choose_output_json_path():
                print("Save cancelled.")
                return False

        self.sync_current_image_record()

        existing_records = []
        if os.path.exists(self.output_json) and os.path.getsize(self.output_json) > 0:
            try:
                existing_records = self.load_annotation_records(self.output_json)
            except ValueError as exc:
                messagebox.showerror("Save Error", f"Could not update annotation file:\n{exc}")
                return False

        loaded_record_map = {
            image_path: self.build_annotation_record(image_path)
            for image_path in self.loaded_image_order
        }

        merged_records = []
        saved_paths = set()

        for record in existing_records:
            try:
                existing_image_path = self.normalize_image_path(record.get("image"), os.path.dirname(self.output_json))
            except (TypeError, ValueError):
                merged_records.append(record)
                continue

            if existing_image_path in loaded_record_map:
                merged_records.append(loaded_record_map[existing_image_path])
                saved_paths.add(existing_image_path)
            else:
                merged_records.append(record)

        for image_path in self.loaded_image_order:
            if image_path not in saved_paths:
                merged_records.append(loaded_record_map[image_path])

        with open(self.output_json, "w", encoding="utf-8") as f:
            for record in merged_records:
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")

        print(f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")
        return True

    def save_boxes_json_event(self, _event=None):
        if self.save_boxes_json(prompt_for_path=True):
            messagebox.showinfo("Saved", f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")

    def clear_boxes_event(self, _event=None):
        if not self.boxes:
            return
        confirm = messagebox.askyesno("Clear Boxes", "Clear all bounding boxes for the current image?")
        if confirm:
            self.boxes.clear()
            self.sync_current_image_record()
            self.refresh_image_list(select_path=self.current_image_path)
            self.redraw_overlays()
            self.save_boxes_json()

    def undo_last_box_event(self, _event=None):
        if self.boxes:
            self.boxes.pop()
            self.sync_current_image_record()
            self.refresh_image_list(select_path=self.current_image_path)
            self.redraw_overlays()
            self.save_boxes_json()

    def toggle_legend_event(self, _event=None):
        self.legend_visible = not self.legend_visible
        self.redraw_overlays()


if __name__ == "__main__":
    # Hide root during file picker to avoid odd UX flash
    picker_root = tk.Tk()
    picker_root.withdraw()
    selected_paths = filedialog.askopenfilenames(
        title="Select image file(s) or a JSONL annotation file",
        filetypes=[
            ("Supported files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.jsonl"),
            ("JSON Lines files", "*.jsonl"),
            ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff"),
            ("All files", "*.*")
        ]
    )

    if selected_paths:
        if len(selected_paths) == 1 and selected_paths[0].lower().endswith(".jsonl"):
            image_records, selected_image_path = ImageBboxSelector.read_annotation_file(selected_paths[0], parent=picker_root)
            picker_root.destroy()
            ImageBboxSelector(
                output_json=selected_paths[0],
                image_records=image_records,
                selected_image_path=selected_image_path,
            )
        else:
            image_paths = [path for path in selected_paths if ImageBboxSelector.is_supported_image_path(path)]
            picker_root.destroy()
            if image_paths:
                ImageBboxSelector(image_paths=image_paths)
    else:
        picker_root.destroy()