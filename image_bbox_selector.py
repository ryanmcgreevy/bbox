import json
import os
import posixpath
import tkinter as tk
from tkinter import filedialog, simpledialog, messagebox, ttk
from PIL import Image, ImageTk

try:
    import fsspec
except ImportError:
    fsspec = None


class LabelEntryDialog(simpledialog.Dialog):
    def __init__(self, parent, title, prompt_text, existing_labels=None, initialvalue=""):
        self.prompt_text = prompt_text
        self.existing_labels = list(existing_labels or [])
        self.initialvalue = initialvalue
        self.result = None
        super().__init__(parent, title)

    def body(self, master):
        tk.Label(master, text=self.prompt_text, anchor="w", justify="left").grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.label_var = tk.StringVar(value=self.initialvalue)
        self.label_combobox = ttk.Combobox(
            master,
            textvariable=self.label_var,
            values=self.existing_labels,
            state="normal",
            width=40,
        )
        self.label_combobox.grid(row=1, column=0, sticky="ew")
        master.grid_columnconfigure(0, weight=1)

        self.label_combobox.focus_set()
        self.label_combobox.selection_range(0, tk.END)
        return self.label_combobox

    def apply(self):
        self.result = self.label_var.get().strip()


class ImageBboxSelector:
    SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff")
    SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "settings.json")

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
        self.root.protocol("WM_DELETE_WINDOW", self.on_close_request)

        # Loaded image records keyed by absolute image path
        self.loaded_images = {}
        self.loaded_image_order = []
        self.current_image_path = None
        self._updating_image_list = False
        self._updating_label_list = False

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

        # During draw/move operations
        self.current_rect_id = None
        self.start_x = None
        self.start_y = None
        self.drag_mode = None
        self.drag_start_original = None
        self.drag_box_snapshot = None
        self.selected_box_index = None
        self.box_was_moved = False

        # Legend
        self.legend_visible = True
        self.legend_bg_id = None
        self.legend_text_id = None

        # Output annotation file path is chosen via a Save As dialog
        self.output_json = output_json

        # Settings
        self.autosave_enabled = tk.BooleanVar(value=False)
        self.last_used_label = ""
        self.load_user_settings()

        self.autosave_enabled.trace_add("write", self.on_autosave_setting_changed)

        # Main layout
        self.main_frame = tk.Frame(self.root)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.sidebar_frame = tk.Frame(self.main_frame, width=240)
        self.sidebar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 0), pady=8)
        self.sidebar_frame.pack_propagate(False)

        self.image_list_section = tk.Frame(self.sidebar_frame)
        self.image_list_section.pack(fill=tk.BOTH, expand=True)

        self.image_list_label = tk.Label(
            self.image_list_section,
            text="Loaded Images",
            anchor="w",
            font=("Arial", 10, "bold")
        )
        self.image_list_label.pack(fill=tk.X, pady=(0, 4))

        self.image_list_frame = tk.Frame(self.image_list_section)
        self.image_list_frame.pack(fill=tk.BOTH, expand=True)

        self.image_listbox = tk.Listbox(self.image_list_frame, exportselection=False)
        self.image_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.image_listbox.bind("<<ListboxSelect>>", self.on_image_list_select)

        self.image_list_scrollbar = tk.Scrollbar(self.image_list_frame, orient=tk.VERTICAL, command=self.image_listbox.yview)
        self.image_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.image_listbox.config(yscrollcommand=self.image_list_scrollbar.set)

        self.label_list_section = tk.Frame(self.sidebar_frame)
        self.label_list_section.pack(fill=tk.BOTH, expand=True, pady=(8, 0))

        self.label_list_label = tk.Label(
            self.label_list_section,
            text="Labels",
            anchor="w",
            font=("Arial", 10, "bold")
        )
        self.label_list_label.pack(fill=tk.X, pady=(0, 4))

        self.label_list_frame = tk.Frame(self.label_list_section)
        self.label_list_frame.pack(fill=tk.BOTH, expand=True)

        self.label_listbox = tk.Listbox(self.label_list_frame, exportselection=False)
        self.label_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.label_listbox.bind("<<ListboxSelect>>", self.on_label_list_select)

        self.label_list_scrollbar = tk.Scrollbar(self.label_list_frame, orient=tk.VERTICAL, command=self.label_listbox.yview)
        self.label_list_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.label_listbox.config(yscrollcommand=self.label_list_scrollbar.set)

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
        self.canvas.bind("<Double-Button-1>", self.on_double_click)

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
        self.root.bind("e", self.edit_selected_box_label_event)  # Edit selected label
        self.root.bind("<Delete>", self.delete_selected_box_event)  # Delete selected box
        self.root.bind("<BackSpace>", self.delete_selected_box_event)  # Delete selected box
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
    def point_in_box(x, y, box, padding=0):
        return (
            box["x1"] - padding <= x <= box["x2"] + padding
            and box["y1"] - padding <= y <= box["y2"] + padding
        )

    def find_box_at_original_point(self, x, y):
        for index in range(len(self.boxes) - 1, -1, -1):
            if self.point_in_box(x, y, self.boxes[index], padding=4):
                return index
        return None

    def move_box(self, box, delta_x, delta_y):
        width = box["x2"] - box["x1"]
        height = box["y2"] - box["y1"]

        max_x1 = max(0, self.original_w - 1 - width)
        max_y1 = max(0, self.original_h - 1 - height)

        new_x1 = min(max(0, box["x1"] + delta_x), max_x1)
        new_y1 = min(max(0, box["y1"] + delta_y), max_y1)

        return {
            "x1": int(new_x1),
            "y1": int(new_y1),
            "x2": int(new_x1 + width),
            "y2": int(new_y1 + height),
            "label": box.get("label", "")
        }

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
    def is_s3_path(path):
        return str(path or "").strip().lower().startswith("s3://")

    @staticmethod
    def split_s3_url(path):
        normalized = str(path).strip()
        if not normalized.lower().startswith("s3://"):
            raise ValueError(f"Not an S3 URL: {path}")
        bucket_and_key = normalized[5:]
        bucket, _, key = bucket_and_key.partition("/")
        return bucket, key

    @staticmethod
    def build_s3_url(bucket, key=""):
        key = str(key).lstrip("/")
        return f"s3://{bucket}/{key}" if key else f"s3://{bucket}"

    @classmethod
    def join_path(cls, base_path, child_path):
        child_path = str(child_path).strip()
        if cls.is_s3_path(base_path):
            if cls.is_s3_path(child_path):
                return child_path
            bucket, key = cls.split_s3_url(base_path)
            joined_key = posixpath.normpath(posixpath.join("/" + key.lstrip("/"), child_path))
            return cls.build_s3_url(bucket, joined_key.lstrip("/"))
        return os.path.join(base_path, child_path)

    @classmethod
    def get_dirname(cls, path):
        if cls.is_s3_path(path):
            bucket, key = cls.split_s3_url(path)
            return cls.build_s3_url(bucket, posixpath.dirname(key))
        return os.path.dirname(path)

    @classmethod
    def get_basename(cls, path):
        if cls.is_s3_path(path):
            _, key = cls.split_s3_url(path)
            return posixpath.basename(key.rstrip("/"))
        return os.path.basename(path)

    @classmethod
    def normalize_path(cls, path, base_dir=None):
        if not path:
            raise ValueError("A file or folder path is required.")

        path = str(path).strip()
        if cls.is_s3_path(path):
            return path

        if base_dir:
            base_dir = str(base_dir).strip()
            if cls.is_s3_path(base_dir):
                return cls.join_path(base_dir, path)
            if not os.path.isabs(path):
                path = os.path.join(base_dir, path)

        return os.path.abspath(os.path.expanduser(path))

    @classmethod
    def normalize_image_path(cls, image_path, base_dir=None):
        if not image_path:
            raise ValueError("Annotation record does not contain an image path.")
        return cls.normalize_path(image_path, base_dir=base_dir)

    @classmethod
    def require_s3_support(cls, path):
        if cls.is_s3_path(path) and fsspec is None:
            raise RuntimeError("S3 paths require the optional 'fsspec' and 's3fs' packages to be installed.")

    @classmethod
    def path_exists(cls, path):
        if cls.is_s3_path(path):
            cls.require_s3_support(path)
            fs, fs_path = fsspec.core.url_to_fs(path)
            return fs.exists(fs_path)
        return os.path.exists(path)

    @classmethod
    def path_isdir(cls, path):
        if cls.is_s3_path(path):
            cls.require_s3_support(path)
            fs, fs_path = fsspec.core.url_to_fs(path)
            return fs.isdir(fs_path)
        return os.path.isdir(path)

    @classmethod
    def path_getsize(cls, path):
        if cls.is_s3_path(path):
            cls.require_s3_support(path)
            fs, fs_path = fsspec.core.url_to_fs(path)
            return fs.size(fs_path)
        return os.path.getsize(path)

    @classmethod
    def open_path(cls, path, mode="r", encoding=None):
        if cls.is_s3_path(path):
            cls.require_s3_support(path)
            open_kwargs = {}
            if encoding is not None and "b" not in mode:
                open_kwargs["encoding"] = encoding
            return fsspec.open(path, mode=mode, **open_kwargs).open()

        open_kwargs = {}
        if encoding is not None and "b" not in mode:
            open_kwargs["encoding"] = encoding
        return open(path, mode, **open_kwargs)

    @classmethod
    def load_image_copy(cls, image_path):
        image_path = cls.normalize_path(image_path)
        if cls.is_s3_path(image_path):
            with cls.open_path(image_path, "rb") as image_file:
                with Image.open(image_file) as image:
                    return image.copy()

        with Image.open(image_path) as image:
            return image.copy()

    @classmethod
    def list_image_paths_in_folder(cls, folder_path):
        folder_path = cls.normalize_path(folder_path)

        if cls.is_s3_path(folder_path):
            cls.require_s3_support(folder_path)
            fs, fs_path = fsspec.core.url_to_fs(folder_path)
            if not fs.exists(fs_path):
                raise FileNotFoundError(f"Folder or prefix not found: {folder_path}")

            image_paths = []
            for entry in fs.ls(fs_path, detail=True):
                if isinstance(entry, dict):
                    entry_name = entry.get("name") or entry.get("Key") or entry.get("path")
                    if entry.get("type") == "directory":
                        continue
                else:
                    entry_name = str(entry)

                if not entry_name:
                    continue

                candidate_path = fs.unstrip_protocol(entry_name) if hasattr(fs, "unstrip_protocol") else entry_name
                if cls.is_supported_image_path(candidate_path):
                    image_paths.append(candidate_path)

            return sorted(image_paths)

        if not os.path.isdir(folder_path):
            raise NotADirectoryError(f"Folder not found: {folder_path}")

        return [
            os.path.join(folder_path, name)
            for name in sorted(os.listdir(folder_path))
            if cls.is_supported_image_path(name)
        ]

    @classmethod
    def expand_input_paths(cls, input_paths):
        resolved_paths = []
        seen = set()
        normalized_inputs = [cls.normalize_path(path) for path in input_paths if str(path).strip()]

        if len(normalized_inputs) == 1 and normalized_inputs[0].lower().endswith(".jsonl"):
            return normalized_inputs, True

        for path in normalized_inputs:
            if path.lower().endswith(".jsonl"):
                raise ValueError("Open a JSONL annotation file by itself, not mixed with image paths.")

            candidate_paths = [path] if cls.is_supported_image_path(path) else cls.list_image_paths_in_folder(path)
            for candidate_path in candidate_paths:
                if candidate_path not in seen:
                    seen.add(candidate_path)
                    resolved_paths.append(candidate_path)

        return resolved_paths, False

    @classmethod
    def is_supported_image_path(cls, image_path):
        return str(image_path).lower().endswith(cls.SUPPORTED_IMAGE_EXTENSIONS)

    def create_image_record(self, image_path, boxes=None):
        image_path = self.normalize_path(image_path)
        if not self.path_exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        image = self.load_image_copy(image_path)
        width, height = image.size
        image.close()

        return {
            "image": image_path,
            "image_size": {"width": width, "height": height},
            "boxes": [self.validate_box(box) for box in (boxes or [])]
        }

    def get_all_existing_labels(self):
        labels = []
        seen = set()

        for image_path in self.loaded_image_order:
            for box in self.loaded_images.get(image_path, {}).get("boxes", []):
                label = str(box.get("label", "")).strip()
                if label and label not in seen:
                    seen.add(label)
                    labels.append(label)

        return labels

    def prompt_for_box_label(self, title, prompt_text, initialvalue="", remember_result=True):
        dialog = LabelEntryDialog(
            self.root,
            title,
            prompt_text,
            existing_labels=self.get_all_existing_labels(),
            initialvalue=initialvalue,
        )
        if remember_result and dialog.result is not None:
            self.last_used_label = dialog.result
        return dialog.result

    @staticmethod
    def parse_path_entries(raw_value):
        if not raw_value:
            return []

        entries = []
        for line in str(raw_value).replace(",", "\n").splitlines():
            entry = line.strip().strip('"').strip("'")
            if entry:
                entries.append(entry)
        return entries

    @classmethod
    def prompt_for_path_entries(cls, title, prompt_text, parent=None, initialvalue=""):
        raw_value = simpledialog.askstring(
            title,
            prompt_text,
            initialvalue=initialvalue,
            parent=parent,
        )
        return cls.parse_path_entries(raw_value)

    @classmethod
    def prompt_for_startup_paths(cls, parent=None):
        return cls.prompt_for_path_entries(
            "Open Path or S3 URL",
            "Enter one or more image paths, folder paths, JSONL files, or S3 URLs to open.\nUse one per line (or separate with commas).",
            parent=parent,
        )

    def open_paths(self, entered_paths, output_json=None):
        resolved_paths, is_jsonl = self.expand_input_paths(entered_paths)
        if is_jsonl:
            return self.load_boxes_json(json_path=resolved_paths[0])

        if not resolved_paths:
            raise ValueError("No supported image files were found for the provided path(s).")

        self.set_loaded_image_paths(
            resolved_paths,
            output_json=output_json,
            prompt_selection=len(resolved_paths) > 1,
        )
        return True

    def open_path_event(self):
        entered_paths = self.prompt_for_path_entries(
            "Open Path or S3 URL",
            "Enter one or more image paths, folder paths, JSONL files, or S3 URLs.\nUse one per line (or separate with commas).",
            parent=self.root,
        )
        if not entered_paths:
            return

        try:
            self.open_paths(entered_paths)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def choose_output_json_path_from_prompt(self):
        initial_path = self.output_json or self.get_default_output_path()
        entered_path = simpledialog.askstring(
            "Save JSONL to Path or S3 URL",
            "Enter a destination path for the JSON Lines file.\nYou can use a local path or an S3 URL such as s3://bucket/annotations.jsonl.",
            initialvalue=initial_path,
            parent=self.root,
        )
        if entered_path:
            self.output_json = self.normalize_path(entered_path)
            return True
        return False

    @staticmethod
    def prompt_for_image_selection(image_paths, parent=None, prompt_title="Select Image", intro_text="Multiple images are loaded."):
        if not image_paths:
            return None
        if len(image_paths) == 1:
            return image_paths[0]

        prompt_lines = [intro_text, "Enter the number to display:", ""]
        for index, image_path in enumerate(image_paths, start=1):
            prompt_lines.append(f"{index}: {ImageBboxSelector.get_basename(image_path)}")

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

    def load_user_settings(self):
        settings_path = self.SETTINGS_FILE
        if not os.path.exists(settings_path):
            return

        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(settings, dict):
            return

        self.autosave_enabled.set(bool(settings.get("autosave_enabled", False)))

    def save_user_settings(self):
        settings = {
            "autosave_enabled": self.is_autosave_enabled(),
        }

        with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")

    def on_autosave_setting_changed(self, *_args):
        self.save_user_settings()

    def is_autosave_enabled(self):
        autosave_setting = getattr(self, "autosave_enabled", True)
        if hasattr(autosave_setting, "get"):
            return bool(autosave_setting.get())
        return bool(autosave_setting)

    def maybe_autosave(self):
        if self.is_autosave_enabled():
            return self.save_boxes_json()
        return False

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
            selected_image_path = self.normalize_path(selected_image_path)

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
            image_path = self.normalize_path(image_path)
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
            self.image_listbox.insert(tk.END, f"{self.get_basename(image_path)} ({box_count})")

        target_path = select_path or self.current_image_path
        if target_path in self.loaded_image_order:
            index = self.loaded_image_order.index(target_path)
            self.image_listbox.selection_clear(0, tk.END)
            self.image_listbox.selection_set(index)
            self.image_listbox.see(index)

        self._updating_image_list = False

    def refresh_label_list(self, select_index=None):
        self._updating_label_list = True
        self.label_listbox.delete(0, tk.END)

        for index, box in enumerate(self.boxes, start=1):
            label_text = box["label"] if box["label"] else f"box_{index}"
            self.label_listbox.insert(tk.END, f"{index}: {label_text}")

        self.label_listbox.selection_clear(0, tk.END)
        target_index = self.selected_box_index if select_index is None else select_index
        if target_index is not None and 0 <= target_index < len(self.boxes):
            self.label_listbox.selection_set(target_index)
            self.label_listbox.see(target_index)

        self._updating_label_list = False

    def on_image_list_select(self, _event=None):
        if self._updating_image_list:
            return

        selection = self.image_listbox.curselection()
        if not selection:
            return

        image_path = self.loaded_image_order[selection[0]]
        if image_path != self.current_image_path:
            self.display_image_path(image_path)

    def on_label_list_select(self, _event=None):
        if self._updating_label_list:
            return

        selection = self.label_listbox.curselection()
        if not selection:
            return

        selected_index = selection[0]
        if selected_index != self.selected_box_index:
            self.selected_box_index = selected_index
            self.redraw_overlays()

    def display_image_path(self, image_path):
        image_path = self.normalize_path(image_path)
        if image_path not in self.loaded_images:
            raise ValueError(f"Image is not loaded: {image_path}")

        self.sync_current_image_record()

        self.original_image = self.load_image_copy(image_path)

        self.current_image_path = image_path
        self.image_path = image_path
        self.original_w, self.original_h = self.original_image.size
        self.current_rect_id = None
        self.start_x = None
        self.start_y = None
        self.drag_mode = None
        self.drag_start_original = None
        self.drag_box_snapshot = None
        self.selected_box_index = None
        self.box_was_moved = False

        self.boxes = [self.validate_box(box) for box in self.loaded_images[image_path].get("boxes", [])]
        self.root.title(f"Image BBox Selector - {self.get_basename(image_path)}")

        self.refresh_image_list(select_path=image_path)
        self.refresh_label_list(select_index=None)
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
        file_menu.add_command(label="Open Path/URL...", command=self.open_path_event)
        file_menu.add_command(label="Open JSONL...", command=self.load_boxes_json_event)
        file_menu.add_separator()
        file_menu.add_command(label="Save JSONL...", command=self.save_boxes_json_event)
        file_menu.add_command(label="Save JSONL to Path/URL...", command=self.save_boxes_json_to_path_event)
        file_menu.add_separator()
        file_menu.add_command(label="Clear Boxes", command=self.clear_boxes_event)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_close_request)

        edit_menu = tk.Menu(menubar, tearoff=0)
        edit_menu.add_command(label="Edit Selected Label", command=self.edit_selected_box_label_event)
        edit_menu.add_command(label="Delete Selected Box", command=self.delete_selected_box_event)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_checkbutton(label="Autosave", variable=self.autosave_enabled, onvalue=True, offvalue=False)

        menubar.add_cascade(label="File", menu=file_menu)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        menubar.add_cascade(label="Settings", menu=settings_menu)
        self.root.config(menu=menubar)

    # -----------------------------
    # Drawing & events
    # -----------------------------
    def on_button_press(self, event):
        if self.original_image is None:
            return

        click_ox, click_oy = self.display_to_original(event.x, event.y)
        hit_index = self.find_box_at_original_point(click_ox, click_oy)

        self.drag_mode = None
        self.box_was_moved = False

        if self.current_rect_id is not None:
            self.canvas.delete(self.current_rect_id)
            self.current_rect_id = None

        if hit_index is not None:
            self.selected_box_index = hit_index
            self.drag_mode = "move"
            self.drag_start_original = (click_ox, click_oy)
            self.drag_box_snapshot = dict(self.boxes[hit_index])
            self.refresh_label_list(select_index=hit_index)
            self.redraw_overlays()
            return

        self.selected_box_index = None
        self.drag_start_original = None
        self.drag_box_snapshot = None
        self.start_x, self.start_y = event.x, event.y
        self.drag_mode = "draw"
        self.current_rect_id = self.canvas.create_rectangle(
            self.start_x, self.start_y, self.start_x, self.start_y,
            outline="red", width=2, tags="temp_rect"
        )
        self.refresh_label_list(select_index=None)
        self.redraw_overlays()

    def on_mouse_drag(self, event):
        if self.drag_mode == "move" and self.selected_box_index is not None and self.drag_start_original and self.drag_box_snapshot:
            current_ox, current_oy = self.display_to_original(event.x, event.y)
            delta_x = current_ox - self.drag_start_original[0]
            delta_y = current_oy - self.drag_start_original[1]
            moved_box = self.move_box(self.drag_box_snapshot, delta_x, delta_y)
            self.box_was_moved = moved_box != self.drag_box_snapshot
            self.boxes[self.selected_box_index] = moved_box
            self.redraw_overlays()
            return

        if self.drag_mode == "draw" and self.current_rect_id is not None:
            self.canvas.coords(self.current_rect_id, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        if self.drag_mode == "move":
            self.drag_mode = None
            self.drag_start_original = None
            self.drag_box_snapshot = None
            self.refresh_label_list(select_index=self.selected_box_index)
            if self.box_was_moved:
                self.sync_current_image_record()
                self.refresh_image_list(select_path=self.current_image_path)
                self.redraw_overlays()
                self.maybe_autosave()
            else:
                self.redraw_overlays()
            return

        if self.drag_mode != "draw" or self.start_x is None or self.start_y is None:
            return

        self.drag_mode = None
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
            self.start_x = None
            self.start_y = None
            return

        # Ask label, with a dropdown of existing labels for reuse
        label = self.prompt_for_box_label(
            "Box Label",
            "Enter label for this box:",
            initialvalue=self.last_used_label,
            remember_result=True,
        )
        if label is None:
            label = ""  # user cancelled -> empty label

        self.boxes.append({
            "x1": ox1, "y1": oy1, "x2": ox2, "y2": oy2, "label": label
        })
        self.selected_box_index = len(self.boxes) - 1

        # Remove temp rectangle and redraw persistent overlays
        if self.current_rect_id is not None:
            self.canvas.delete(self.current_rect_id)
            self.current_rect_id = None

        self.start_x = None
        self.start_y = None
        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.refresh_label_list(select_index=self.selected_box_index)
        self.redraw_overlays()
        self.maybe_autosave()

    def on_double_click(self, event):
        if self.original_image is None:
            return

        click_ox, click_oy = self.display_to_original(event.x, event.y)
        hit_index = self.find_box_at_original_point(click_ox, click_oy)
        if hit_index is not None:
            self.selected_box_index = hit_index
            self.refresh_label_list(select_index=hit_index)
            self.redraw_overlays()
            self.edit_selected_box_label_event()

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
            is_selected = (i - 1 == self.selected_box_index)
            outline_color = "cyan" if is_selected else "red"
            label_color = "cyan" if is_selected else "red"
            line_width = 3 if is_selected else 2

            self.canvas.create_rectangle(
                dx1, dy1, dx2, dy2,
                outline=outline_color, width=line_width, tags="box"
            )

            # Label text shown near top-left of box
            label_text = b["label"] if b["label"] else f"box_{i}"
            self.canvas.create_text(
                dx1 + 4, max(10, dy1 - 8),
                text=label_text,
                fill=label_color,
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
            "Shortcuts: S=Save  L=Load  E=Edit Label  Del=Delete  H=Hide/Show\n"
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
    @classmethod
    def load_annotation_records(cls, annotation_path):
        annotation_path = cls.normalize_path(annotation_path)
        records = []
        with cls.open_path(annotation_path, "r", encoding="utf-8") as f:
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
        annotation_path = cls.normalize_path(annotation_path)
        raw_records = cls.load_annotation_records(annotation_path)
        image_records = []
        image_paths = []
        annotation_dir = cls.get_dirname(annotation_path)

        for record in raw_records:
            image_path = cls.normalize_image_path(record.get("image"), annotation_dir)
            if not cls.path_exists(image_path):
                raise FileNotFoundError(f"Image not found: {image_path}")

            image = cls.load_image_copy(image_path)
            width, height = image.size
            image.close()

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

        image_path = self.normalize_path(image_path or self.current_image_path)
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
        image_dir = self.get_dirname(self.image_path) or "."
        image_name = os.path.splitext(self.get_basename(self.image_path))[0]
        return self.join_path(image_dir, f"{image_name}_bounding_boxes.jsonl")

    def choose_output_json_path(self):
        initial_path = self.output_json or self.get_default_output_path()

        dialog_initialdir = os.path.dirname(self.SETTINGS_FILE) or "."
        if self.image_path and not self.is_s3_path(self.image_path):
            dialog_initialdir = self.get_dirname(self.image_path) or dialog_initialdir

        if initial_path and not self.is_s3_path(initial_path):
            dialog_initialdir = self.get_dirname(initial_path) or dialog_initialdir

        dialog_initialfile = self.get_basename(initial_path) or "annotations.jsonl"

        selected_path = filedialog.asksaveasfilename(
            title="Save bounding boxes JSON Lines",
            defaultextension=".jsonl",
            initialdir=dialog_initialdir,
            initialfile=dialog_initialfile,
            filetypes=[("JSON Lines files", "*.jsonl"), ("All files", "*.*")]
        )
        if selected_path:
            self.output_json = self.normalize_path(selected_path)
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

        json_path = self.normalize_path(json_path)
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
            self.open_paths(image_paths)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def open_folder_event(self):
        folder_path = filedialog.askdirectory(title="Open folder of images")
        if not folder_path:
            return

        try:
            image_paths = self.list_image_paths_in_folder(folder_path)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))
            return

        if not image_paths:
            messagebox.showinfo("No Images Found", "No supported image files were found in the selected folder.")
            return

        try:
            self.set_loaded_image_paths(image_paths, output_json=None, prompt_selection=len(image_paths) > 1)
        except Exception as exc:
            messagebox.showerror("Load Error", str(exc))

    def edit_selected_box_label_event(self, _event=None):
        if self.selected_box_index is None or not (0 <= self.selected_box_index < len(self.boxes)):
            return

        current_label = self.boxes[self.selected_box_index].get("label", "")
        new_label = self.prompt_for_box_label(
            "Edit Box Label",
            "Update label for the selected box:",
            initialvalue=current_label,
            remember_result=True,
        )
        if new_label is None:
            return

        self.boxes[self.selected_box_index]["label"] = new_label
        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.refresh_label_list(select_index=self.selected_box_index)
        self.redraw_overlays()
        self.maybe_autosave()

    def delete_selected_box_event(self, _event=None):
        if self.selected_box_index is None or not (0 <= self.selected_box_index < len(self.boxes)):
            return

        label = self.boxes[self.selected_box_index].get("label", "")
        confirm_message = "Delete the selected bounding box?"
        if label:
            confirm_message = f"Delete the selected bounding box labeled '{label}'?"

        if not messagebox.askyesno("Delete Box", confirm_message, parent=self.root):
            return

        self.boxes.pop(self.selected_box_index)
        self.selected_box_index = None
        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.refresh_label_list(select_index=None)
        self.redraw_overlays()
        self.maybe_autosave()

    def save_boxes_json(self, prompt_for_path=False):
        if prompt_for_path or not self.output_json:
            if not self.choose_output_json_path():
                print("Save cancelled.")
                return False

        self.output_json = self.normalize_path(self.output_json)
        self.sync_current_image_record()

        existing_records = []
        if self.path_exists(self.output_json) and self.path_getsize(self.output_json) > 0:
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
                existing_image_path = self.normalize_image_path(record.get("image"), self.get_dirname(self.output_json))
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

        with self.open_path(self.output_json, "w", encoding="utf-8") as f:
            for record in merged_records:
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")

        print(f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")
        return True

    def save_boxes_json_event(self, _event=None):
        if self.save_boxes_json(prompt_for_path=True):
            messagebox.showinfo("Saved", f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")

    def save_boxes_json_to_path_event(self):
        if self.choose_output_json_path_from_prompt() and self.save_boxes_json(prompt_for_path=False):
            messagebox.showinfo("Saved", f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")

    def clear_boxes_event(self, _event=None):
        if not self.boxes:
            return
        confirm = messagebox.askyesno("Clear Boxes", "Clear all bounding boxes for the current image?")
        if confirm:
            self.boxes.clear()
            self.selected_box_index = None
            self.sync_current_image_record()
            self.refresh_image_list(select_path=self.current_image_path)
            self.refresh_label_list(select_index=None)
            self.redraw_overlays()
            self.maybe_autosave()

    def undo_last_box_event(self, _event=None):
        if self.boxes:
            self.boxes.pop()
            if self.selected_box_index is not None and self.selected_box_index >= len(self.boxes):
                self.selected_box_index = len(self.boxes) - 1 if self.boxes else None
            self.sync_current_image_record()
            self.refresh_image_list(select_path=self.current_image_path)
            self.refresh_label_list(select_index=self.selected_box_index)
            self.redraw_overlays()
            self.maybe_autosave()

    def toggle_legend_event(self, _event=None):
        self.legend_visible = not self.legend_visible
        self.redraw_overlays()

    def on_close_request(self):
        answer = messagebox.askyesnocancel(
            "Save Before Exit",
            "Would you like to save the annotations to a file before closing?",
            parent=self.root,
        )

        if answer is None:
            return

        if answer:
            if not self.save_boxes_json(prompt_for_path=True):
                return

        self.root.destroy()


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

    entered_paths = []
    if not selected_paths:
        entered_paths = ImageBboxSelector.prompt_for_startup_paths(parent=picker_root)

    picker_root.destroy()

    try:
        if selected_paths:
            if len(selected_paths) == 1 and selected_paths[0].lower().endswith(".jsonl"):
                json_path = ImageBboxSelector.normalize_path(selected_paths[0])
                image_records, selected_image_path = ImageBboxSelector.read_annotation_file(json_path)
                ImageBboxSelector(
                    output_json=json_path,
                    image_records=image_records,
                    selected_image_path=selected_image_path,
                )
            else:
                image_paths = [path for path in selected_paths if ImageBboxSelector.is_supported_image_path(path)]
                if image_paths:
                    ImageBboxSelector(image_paths=image_paths)
        elif entered_paths:
            resolved_paths, is_jsonl = ImageBboxSelector.expand_input_paths(entered_paths)
            if is_jsonl:
                json_path = resolved_paths[0]
                image_records, selected_image_path = ImageBboxSelector.read_annotation_file(json_path)
                ImageBboxSelector(
                    output_json=json_path,
                    image_records=image_records,
                    selected_image_path=selected_image_path,
                )
            elif resolved_paths:
                ImageBboxSelector(image_paths=resolved_paths)
    except Exception as exc:
        messagebox.showerror("Load Error", str(exc))