import json
import os
import posixpath
import sys
from PIL import Image, ImageDraw, ImageFont

from PyQt6.QtCore import Qt, QRect
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
    QFrame, QHBoxLayout, QInputDialog, QLabel, QListWidget, QMainWindow,
    QMessageBox, QSizePolicy, QVBoxLayout, QWidget,
)
from PyQt6.QtGui import (
    QAction, QBrush, QColor, QFont, QFontMetrics, QImage,
    QPainter, QPen, QPixmap,
)

try:
    import fsspec
except ImportError:
    fsspec = None



class LabelEntryDialog(QDialog):
    """Dialog for entering or selecting a label from existing labels."""

    def __init__(self, parent, title, prompt_text, existing_labels=None, initialvalue=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.result = None
        self.existing_labels = list(existing_labels or [])

        layout = QVBoxLayout(self)

        prompt_label = QLabel(prompt_text)
        prompt_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(prompt_label)

        self.combobox = QComboBox()
        self.combobox.setEditable(True)
        self.combobox.addItems(self.existing_labels)
        self.combobox.setCurrentText(initialvalue)
        self.combobox.setMinimumWidth(300)
        layout.addWidget(self.combobox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.combobox.setFocus()
        if self.combobox.lineEdit():
            self.combobox.lineEdit().selectAll()

    def _on_accept(self):
        self.result = self.combobox.currentText().strip()
        self.accept()


class ImageSelectionDialog(QDialog):
    """Dialog for selecting which loaded image should be displayed first."""

    def __init__(self, parent, title, image_paths, intro_text="Multiple images are loaded."):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.image_paths = list(image_paths or [])
        self.result = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(intro_text))
        layout.addWidget(QLabel("Select the image to display first:"))

        self.listbox = QListWidget()
        height = min(max(len(self.image_paths), 6), 16)
        self.listbox.setMinimumHeight(height * 22)
        self.listbox.setMinimumWidth(400)

        for index, image_path in enumerate(self.image_paths, start=1):
            self.listbox.addItem(f"{index}: {ImageBboxSelector.get_basename(image_path)}")

        if self.image_paths:
            self.listbox.setCurrentRow(0)

        self.listbox.itemDoubleClicked.connect(self._on_double_click)
        layout.addWidget(self.listbox)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.listbox.setFocus()

    def _on_double_click(self, _item=None):
        self._on_accept()

    def _on_accept(self):
        row = self.listbox.currentRow()
        if row >= 0:
            self.result = self.image_paths[row]
        self.accept()


class BBoxCanvas(QWidget):
    """Widget that displays the image and bounding box overlays."""

    def __init__(self, selector):
        super().__init__()
        self.selector = selector
        self._pixmap = None
        self._temp_rect = None  # (x1, y1, x2, y2) in widget coords while drawing
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_pixmap(self, pixmap):
        self._pixmap = pixmap
        self.update()

    def clear_pixmap(self):
        self._pixmap = None
        self.update()

    def set_temp_rect(self, rect):
        """rect = (x1, y1, x2, y2) in widget coords, or None."""
        self._temp_rect = rect
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("black"))

        if self._pixmap is None:
            font = QFont("Arial", 16, QFont.Weight.Bold)
            painter.setFont(font)
            painter.setPen(QColor("white"))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "No image loaded.\nUse the File menu to open image(s), a folder, or a JSONL file.",
            )
            painter.end()
            return

        painter.drawPixmap(0, 0, self._pixmap)

        sel = self.selector
        font_size, line_width, text_padding = sel.get_display_annotation_style()
        ann_font = QFont("Arial", font_size, QFont.Weight.Bold)
        metrics = QFontMetrics(ann_font)
        painter.setFont(ann_font)

        for i, b in enumerate(sel.boxes):
            is_selected = (i == sel.selected_box_index)
            outline_color = QColor("cyan") if is_selected else QColor("red")
            label_bg = QColor("cyan") if is_selected else QColor("red")
            label_fg = QColor("black") if is_selected else QColor("white")
            lw = line_width + (1 if is_selected else 0)

            dx1, dy1 = sel.original_to_display(b["x1"], b["y1"])
            dx2, dy2 = sel.original_to_display(b["x2"], b["y2"])

            painter.setPen(QPen(outline_color, lw))
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawRect(int(dx1), int(dy1), int(dx2 - dx1), int(dy2 - dy1))

            label_text = b["label"] if b["label"] else f"box_{i + 1}"
            text_x = int(dx1) + text_padding
            text_y = max(2, int(dy1) - font_size - text_padding * 2)

            text_w = metrics.horizontalAdvance(label_text)
            text_h = metrics.height()
            vertical_pad = max(2, text_padding // 2)

            bg_rect = QRect(
                text_x,
                text_y + text_padding - vertical_pad,
                text_w + text_padding * 2,
                text_h + vertical_pad * 2,
            )
            painter.fillRect(bg_rect, label_bg)
            painter.setPen(label_fg)
            painter.drawText(
                text_x + text_padding,
                text_y + text_padding + metrics.ascent(),
                label_text,
            )

        if self._temp_rect is not None:
            x1, y1, x2, y2 = self._temp_rect
            painter.setPen(QPen(QColor("red"), 2))
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawRect(int(min(x1, x2)), int(min(y1, y2)), int(abs(x2 - x1)), int(abs(y2 - y1)))

        if sel.legend_visible:
            sel._draw_legend_qt(painter)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self.selector.on_button_press(pos.x(), pos.y())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            pos = event.position()
            self.selector.on_mouse_drag(pos.x(), pos.y())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self.selector.on_button_release(pos.x(), pos.y())

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self.selector.on_double_click(pos.x(), pos.y())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.selector.on_canvas_resize(event.size().width(), event.size().height())


class ImageBboxSelector(QMainWindow):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Qt6-based bounding-box annotation tool for loading, editing,
    and exporting image annotations."""

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
        self._app = QApplication.instance() or QApplication(sys.argv)
        super().__init__()
        self.setWindowTitle("Image BBox Selector")

        # Loaded image records keyed by image path; full image data is cached lazily
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
        self.display_w = 800
        self.display_h = 600
        self.window_size_initialized = False

        # Bounding boxes are stored in ORIGINAL image coordinates
        self.boxes = []

        # During draw/move operations
        self.start_x = None
        self.start_y = None
        self.drag_mode = None
        self.drag_start_original = None
        self.drag_box_snapshot = None
        self.selected_box_index = None
        self.box_was_moved = False

        # Legend
        self.legend_visible = True

        # Output annotation file path is chosen via a Save As dialog
        self.output_json = output_json
        self.annotation_state_snapshot = None
        self.last_exported_image_path = None

        # Settings
        self._autosave_enabled = False
        self.last_used_label = ""
        self.load_user_settings()

        # Build the UI
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(8)

        # Sidebar
        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(4)

        image_list_label = QLabel("Loaded Images")
        image_list_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        sidebar_layout.addWidget(image_list_label)

        self.image_listbox = QListWidget()
        self.image_listbox.currentRowChanged.connect(self._on_image_list_row_changed)
        sidebar_layout.addWidget(self.image_listbox, stretch=1)

        label_list_label = QLabel("Labels")
        label_list_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        sidebar_layout.addWidget(label_list_label)

        self.label_listbox = QListWidget()
        self.label_listbox.currentRowChanged.connect(self._on_label_list_row_changed)
        sidebar_layout.addWidget(self.label_listbox, stretch=1)

        root_layout.addWidget(self.sidebar_frame)

        # Canvas
        self.canvas = BBoxCanvas(self)
        root_layout.addWidget(self.canvas, stretch=1)

        # Menu bar
        self.create_menu_bar()

        # Initial load
        self.show()
        QApplication.processEvents()

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
            self.initialize_empty_state()

        self._app.exec()

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

    def initialize_empty_state(self):
        screen = QApplication.primaryScreen().size()
        screen_w, screen_h = screen.width(), screen.height()
        window_w = min(max(960, int(screen_w * 0.8)), max(640, screen_w - 40))
        window_h = min(max(700, int(screen_h * 0.8)), max(480, screen_h - 60))
        x = max((screen_w - int(window_w)) // 2, 0)
        y = max((screen_h - int(window_h)) // 2, 0)
        self.setGeometry(x, y, int(window_w), int(window_h))
        self.window_size_initialized = True
        self.show_empty_canvas_message()
        self.mark_annotation_state_saved()

    def show_empty_canvas_message(self):
        self.canvas.clear_pixmap()

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
    def get_label_display_bbox(self, index):
        if not (0 <= index < len(self.boxes)):
            return None

        display_font_size, _, text_padding = self.get_display_annotation_style()
        box = self.boxes[index]
        dx1, dy1 = self.original_to_display(box["x1"], box["y1"])
        label_text = box["label"] if box["label"] else f"box_{index + 1}"

        text_x = dx1 + text_padding
        text_y = max(2, dy1 - display_font_size - (text_padding * 2))

        font = QFont("Arial", display_font_size, QFont.Weight.Bold)
        metrics = QFontMetrics(font)
        text_w = metrics.horizontalAdvance(label_text)
        text_h = metrics.height()

        vertical_pad = max(2, text_padding // 2)
        return (
            text_x,
            text_y + text_padding - vertical_pad,
            text_x + text_w + (text_padding * 2),
            text_y + text_padding + text_h + vertical_pad,
        )

    @staticmethod
    def point_in_display_rect(x, y, rect):
        if rect is None:
            return False
        x1, y1, x2, y2 = rect
        return x1 <= x <= x2 and y1 <= y <= y2

    def find_box_or_label_at_display_point(self, x, y):
        for index in range(len(self.boxes) - 1, -1, -1):
            label_bbox = self.get_label_display_bbox(index)
            if self.point_in_display_rect(x, y, label_bbox):
                return index

            box = self.boxes[index]
            dx1, dy1 = self.original_to_display(box["x1"], box["y1"])
            dx2, dy2 = self.original_to_display(box["x2"], box["y2"])
            if self.point_in_display_rect(x, y, self.normalize_box(dx1, dy1, dx2, dy2)):
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
    def get_image_size(cls, image_path):
        image_path = cls.normalize_path(image_path)
        if cls.is_s3_path(image_path):
            with cls.open_path(image_path, "rb") as image_file:
                with Image.open(image_file) as image:
                    return image.size

        with Image.open(image_path) as image:
            return image.size

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

    def create_image_record(self, image_path, boxes=None, image_size=None):
        image_path = self.normalize_path(image_path)
        if not self.path_exists(image_path):
            raise FileNotFoundError(f"Image not found: {image_path}")

        normalized_size = image_size or {}
        width = normalized_size.get("width")
        height = normalized_size.get("height")
        if width is None or height is None:
            width, height = self.get_image_size(image_path)

        return {
            "image": image_path,
            "image_size": {"width": int(width), "height": int(height)},
            "boxes": [self.validate_box(box) for box in (boxes or [])],
            "_cached_image": None,
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
            self,
            title,
            prompt_text,
            existing_labels=self.get_all_existing_labels(),
            initialvalue=initialvalue,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            result = dialog.result
        else:
            result = None
        if remember_result and result is not None:
            self.last_used_label = result
        return result

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
        text, ok = QInputDialog.getText(parent, title, prompt_text, text=initialvalue)
        if not ok:
            return []
        return cls.parse_path_entries(text)

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
            parent=self,
        )
        if not entered_paths:
            return

        try:
            self.open_paths(entered_paths)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))

    def choose_output_json_path_from_prompt(self):
        initial_path = self.output_json or self.get_default_output_path()
        entered_path, ok = QInputDialog.getText(
            self,
            "Save JSONL to Path or S3 URL",
            "Enter a destination path for the JSON Lines file.\nYou can use a local path or an S3 URL such as s3://bucket/annotations.jsonl.",
            text=initial_path,
        )
        if ok and entered_path:
            self.output_json = self.normalize_path(entered_path.strip())
            return True
        return False

    @staticmethod
    def prompt_for_image_selection(
        image_paths,
        parent=None,
        prompt_title="Select Image",
        intro_text="Multiple images are loaded.",
    ):
        if not image_paths:
            return None
        if len(image_paths) == 1:
            return image_paths[0]

        dialog = ImageSelectionDialog(
            parent,
            prompt_title,
            image_paths,
            intro_text=intro_text,
        )
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if not accepted or dialog.result is None:
            return image_paths[0]
        return dialog.result

    def sync_current_image_record(self):
        if self.current_image_path and self.current_image_path in self.loaded_images:
            self.loaded_images[self.current_image_path]["boxes"] = [self.validate_box(box) for box in self.boxes]
            self.loaded_images[self.current_image_path]["image_size"] = {
                "width": int(self.original_w),
                "height": int(self.original_h)
            }

    def snapshot_annotation_state(self):
        self.sync_current_image_record()

        snapshot = []
        for image_path in self.loaded_image_order:
            record = self.loaded_images.get(image_path, {})
            image_size = record.get("image_size") or {}
            snapshot.append({
                "image": self.normalize_path(image_path),
                "image_size": {
                    "width": int(image_size.get("width", 0)),
                    "height": int(image_size.get("height", 0)),
                },
                "boxes": [self.validate_box(box) for box in record.get("boxes", [])],
            })

        return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)

    def mark_annotation_state_saved(self):
        self.annotation_state_snapshot = self.snapshot_annotation_state()

    def has_unsaved_annotation_changes(self):
        if self.annotation_state_snapshot is None:
            self.mark_annotation_state_saved()
            return False
        return self.snapshot_annotation_state() != self.annotation_state_snapshot

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

        self._autosave_enabled = bool(settings.get("autosave_enabled", False))

    def save_user_settings(self):
        settings = {
            "autosave_enabled": self.is_autosave_enabled(),
        }

        with open(self.SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
            f.write("\n")

    def on_autosave_setting_changed(self):
        self.save_user_settings()

    def is_autosave_enabled(self):
        return bool(getattr(self, "_autosave_enabled", False))

    def maybe_autosave(self):
        if self.is_autosave_enabled():
            return self.save_boxes_json()
        return False

    def set_loaded_records(self, image_records, selected_image_path=None, output_json=None, prompt_selection=False):
        normalized_records = []

        for record in image_records:
            image_path = self.normalize_image_path(record.get("image"))
            image_size = record.get("image_size") or {}
            normalized_record = self.create_image_record(
                image_path,
                boxes=record.get("boxes", []),
                image_size=image_size,
            )

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
                    parent=self,
                    prompt_title="Select Image",
                    intro_text="Multiple images are loaded."
                )
            else:
                selected_image_path = self.loaded_image_order[0]

        self.display_image_path(selected_image_path)
        self.mark_annotation_state_saved()

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
                parent=self,
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
        self.image_listbox.clear()

        for image_path in self.loaded_image_order:
            box_count = len(self.loaded_images[image_path].get("boxes", []))
            self.image_listbox.addItem(f"{self.get_basename(image_path)} ({box_count})")

        target_path = select_path or self.current_image_path
        if target_path in self.loaded_image_order:
            index = self.loaded_image_order.index(target_path)
            self.image_listbox.setCurrentRow(index)
            item = self.image_listbox.item(index)
            if item:
                self.image_listbox.scrollToItem(item)

        self._updating_image_list = False

    def refresh_label_list(self, select_index=None):
        self._updating_label_list = True
        self.label_listbox.clear()

        for index, box in enumerate(self.boxes, start=1):
            label_text = box["label"] if box["label"] else f"box_{index}"
            self.label_listbox.addItem(f"{index}: {label_text}")

        self.label_listbox.clearSelection()
        target_index = self.selected_box_index if select_index is None else select_index
        if target_index is not None and 0 <= target_index < len(self.boxes):
            self.label_listbox.setCurrentRow(target_index)
            item = self.label_listbox.item(target_index)
            if item:
                self.label_listbox.scrollToItem(item)

        self._updating_label_list = False

    def _on_image_list_row_changed(self, row):
        if self._updating_image_list or row < 0:
            return
        if row >= len(self.loaded_image_order):
            return
        image_path = self.loaded_image_order[row]
        if image_path != self.current_image_path:
            self.display_image_path(image_path)

    def on_image_list_select(self, _event=None):
        """Kept for API compatibility; internal use goes through _on_image_list_row_changed."""
        self._on_image_list_row_changed(self.image_listbox.currentRow())

    def _on_label_list_row_changed(self, row):
        if self._updating_label_list or row < 0:
            return
        if row != self.selected_box_index:
            self.selected_box_index = row
            self.redraw_overlays()

    def on_label_list_select(self, _event=None):
        """Kept for API compatibility; internal use goes through _on_label_list_row_changed."""
        self._on_label_list_row_changed(self.label_listbox.currentRow())

    def display_image_path(self, image_path):
        image_path = self.normalize_path(image_path)
        if image_path not in self.loaded_images:
            raise ValueError(f"Image is not loaded: {image_path}")

        self.sync_current_image_record()

        record = self.loaded_images[image_path]
        cached_image = record.get("_cached_image")
        if cached_image is None:
            cached_image = self.load_image_copy(image_path)
            record["_cached_image"] = cached_image
            record["image_size"] = {
                "width": int(cached_image.size[0]),
                "height": int(cached_image.size[1]),
            }

        self.original_image = cached_image

        self.current_image_path = image_path
        self.image_path = image_path
        self.original_w, self.original_h = self.original_image.size
        self.start_x = None
        self.start_y = None
        self.drag_mode = None
        self.drag_start_original = None
        self.drag_box_snapshot = None
        self.selected_box_index = None
        self.box_was_moved = False
        self.canvas.set_temp_rect(None)

        self.boxes = [
            self.validate_box(box) for box in self.loaded_images[image_path].get("boxes", [])
        ]
        self.setWindowTitle(f"Image BBox Selector - {self.get_basename(image_path)}")

        self.refresh_image_list(select_path=image_path)
        self.refresh_label_list(select_index=None)
        if not self.window_size_initialized:
            self.set_initial_window_size()
            self.window_size_initialized = True
        else:
            QApplication.processEvents()
        self.update_canvas_image()
        self.redraw_overlays()

    @staticmethod
    def _pil_to_qpixmap(pil_image):
        """Convert a PIL Image to a QPixmap."""
        pil_rgba = pil_image.convert("RGBA")
        data = pil_rgba.tobytes("raw", "RGBA")
        qimage = QImage(
            data,
            pil_rgba.width,
            pil_rgba.height,
            pil_rgba.width * 4,
            QImage.Format.Format_RGBA8888,
        )
        return QPixmap.fromImage(qimage)

    def update_canvas_image(self, available_width=None, available_height=None):
        if self.original_image is None:
            return

        if available_width is None:
            available_width = self.canvas.width()
        if available_height is None:
            available_height = self.canvas.height()

        available_width = max(1, int(available_width))
        available_height = max(1, int(available_height))

        if available_width < 2 or available_height < 2:
            return

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
            self.display_image = self.original_image.resize(
                (self.display_w, self.display_h), Image.Resampling.LANCZOS
            )

        pixmap = self._pil_to_qpixmap(self.display_image)
        self.canvas.set_pixmap(pixmap)

    def is_window_fullscreen(self):
        return self.isFullScreen() or self.isMaximized()

    def set_initial_window_size(self):
        if self.is_window_fullscreen():
            return

        screen = QApplication.primaryScreen().size()
        screen_w, screen_h = screen.width(), screen.height()

        sidebar_w = 240
        max_canvas_w = max(400, screen_w - sidebar_w - 60)
        max_canvas_h = max(300, screen_h - 100)

        scale = min(
            max_canvas_w / max(1, self.original_w),
            max_canvas_h / max(1, self.original_h),
            1.0,
        )
        target_canvas_w = max(1, int(round(self.original_w * scale)))
        target_canvas_h = max(1, int(round(self.original_h * scale)))

        window_w = min(target_canvas_w + sidebar_w + 40, screen_w - 20)
        window_h = min(target_canvas_h + 80, screen_h - 40)

        x = max((screen_w - int(window_w)) // 2, 0)
        y = max((screen_h - int(window_h)) // 2, 0)
        self.setGeometry(x, y, int(window_w), int(window_h))
        QApplication.processEvents()

    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        file_menu.addAction("Open Image(s)...", self.open_image_event)
        file_menu.addAction("Open Folder...", self.open_folder_event)
        file_menu.addAction("Open Path/URL...", self.open_path_event)
        file_menu.addAction("Open JSONL...", self.load_boxes_json_event)
        file_menu.addSeparator()
        file_menu.addAction("Save JSONL...", self.save_boxes_json_event)
        file_menu.addAction("Save JSONL to Path/URL...", self.save_boxes_json_to_path_event)
        file_menu.addAction("Export Annotated Image...", self.save_annotated_image_event)
        file_menu.addSeparator()
        file_menu.addAction("Clear Boxes", self.clear_boxes_event)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)

        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction("Edit Selected Label", self.edit_selected_box_label_event)
        edit_menu.addAction("Delete Selected Box", self.delete_selected_box_event)

        settings_menu = menubar.addMenu("Settings")
        self._autosave_action = QAction("Autosave", self, checkable=True)
        self._autosave_action.setChecked(self._autosave_enabled)
        self._autosave_action.triggered.connect(self._on_autosave_action_toggled)
        settings_menu.addAction(self._autosave_action)

    def _on_autosave_action_toggled(self, checked):
        self._autosave_enabled = bool(checked)
        self.on_autosave_setting_changed()

    # -----------------------------
    # Keyboard shortcuts
    # -----------------------------
    def keyPressEvent(self, event):
        key = event.key()
        modifiers = event.modifiers()

        if key == Qt.Key.Key_S:
            self.save_boxes_json_event()
        elif key == Qt.Key.Key_C:
            self.clear_boxes_event()
        elif key == Qt.Key.Key_U:
            self.undo_last_box_event()
        elif key == Qt.Key.Key_Z and modifiers & Qt.KeyboardModifier.ControlModifier:
            self.undo_last_box_event()
        elif key == Qt.Key.Key_L:
            self.load_boxes_json_event()
        elif key == Qt.Key.Key_E:
            self.edit_selected_box_label_event()
        elif key == Qt.Key.Key_D:
            self.delete_selected_box_event()
        elif key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selected_box_event()
        elif key == Qt.Key.Key_H:
            self.toggle_legend_event()
        else:
            super().keyPressEvent(event)

    # -----------------------------
    # Window close
    # -----------------------------
    def closeEvent(self, event):
        if not self.has_unsaved_annotation_changes():
            event.accept()
            return

        msgbox = QMessageBox(self)
        msgbox.setWindowTitle("Save Before Exit")
        msgbox.setText("Would you like to save the annotations to a file before closing?")
        yes_btn = msgbox.addButton(QMessageBox.StandardButton.Yes)
        no_btn = msgbox.addButton(QMessageBox.StandardButton.No)
        cancel_btn = msgbox.addButton(QMessageBox.StandardButton.Cancel)
        msgbox.setDefaultButton(cancel_btn)
        msgbox.exec()

        clicked = msgbox.clickedButton()
        if clicked == cancel_btn:
            event.ignore()
            return

        if clicked == yes_btn:
            if not self.save_boxes_json(prompt_for_path=True):
                event.ignore()
                return

        event.accept()

    # -----------------------------
    # Drawing & events
    # -----------------------------
    def on_button_press(self, x, y):
        if self.original_image is None:
            return

        hit_index = self.find_box_or_label_at_display_point(x, y)
        click_ox, click_oy = self.display_to_original(x, y)

        self.drag_mode = None
        self.box_was_moved = False
        self.canvas.set_temp_rect(None)

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
        self.start_x, self.start_y = x, y
        self.drag_mode = "draw"
        self.canvas.set_temp_rect((x, y, x, y))
        self.refresh_label_list(select_index=None)
        self.redraw_overlays()

    def on_mouse_drag(self, x, y):
        if (
            self.drag_mode == "move"
            and self.selected_box_index is not None
            and self.drag_start_original
            and self.drag_box_snapshot
        ):
            current_ox, current_oy = self.display_to_original(x, y)
            delta_x = current_ox - self.drag_start_original[0]
            delta_y = current_oy - self.drag_start_original[1]
            moved_box = self.move_box(self.drag_box_snapshot, delta_x, delta_y)
            self.box_was_moved = moved_box != self.drag_box_snapshot
            self.boxes[self.selected_box_index] = moved_box
            self.redraw_overlays()
            return

        if self.drag_mode == "draw" and self.start_x is not None:
            self.canvas.set_temp_rect((self.start_x, self.start_y, x, y))

    def on_button_release(self, x, y):
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
        end_x, end_y = x, y

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
            self.canvas.set_temp_rect(None)
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

        self.boxes.append({"x1": ox1, "y1": oy1, "x2": ox2, "y2": oy2, "label": label})
        self.selected_box_index = len(self.boxes) - 1

        self.canvas.set_temp_rect(None)
        self.start_x = None
        self.start_y = None
        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.refresh_label_list(select_index=self.selected_box_index)
        self.redraw_overlays()
        self.maybe_autosave()

    def on_double_click(self, x, y):
        if self.original_image is None:
            return

        hit_index = self.find_box_or_label_at_display_point(x, y)
        if hit_index is not None:
            self.selected_box_index = hit_index
            self.refresh_label_list(select_index=hit_index)
            self.redraw_overlays()
            self.edit_selected_box_label_event()

    def on_canvas_resize(self, w, h):
        if self.original_image is None:
            self.show_empty_canvas_message()
            return

        if w < 2 or h < 2:
            return

        self.update_canvas_image(w, h)
        self.redraw_overlays()

    @staticmethod
    def clamp_int(value, minimum, maximum):
        return max(minimum, min(maximum, int(round(value))))

    def get_display_annotation_style(self):
        min_dim = min(max(1, self.display_w), max(1, self.display_h))
        font_size = self.clamp_int(min_dim / 18, 12, 28)
        line_width = self.clamp_int(min_dim / 220, 2, 6)
        text_padding = self.clamp_int(min_dim / 120, 4, 14)
        return font_size, line_width, text_padding

    def get_export_annotation_style(self):
        min_dim = min(max(1, self.original_w), max(1, self.original_h))
        font_size = self.clamp_int(min_dim / 18, 12, 72)
        line_width = self.clamp_int(min_dim / 220, 2, 12)
        text_padding = self.clamp_int(min_dim / 120, 4, 20)
        return font_size, line_width, text_padding

    @staticmethod
    def get_text_bbox(draw, text, font):
        try:
            return draw.textbbox((0, 0), text, font=font)
        except AttributeError:
            text_w, text_h = draw.textsize(text, font=font)
            return 0, 0, text_w, text_h

    @staticmethod
    def load_annotation_font(font_size):
        for font_name in ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial.ttf"):
            try:
                return ImageFont.truetype(font_name, int(font_size))
            except OSError:
                continue
        return ImageFont.load_default()

    # -----------------------------
    # Overlay rendering
    # -----------------------------
    def redraw_overlays(self):
        """Trigger a repaint of the canvas widget."""
        self.canvas.update()

    def _draw_legend_qt(self, painter):
        """Draw the shortcut legend overlay onto the given QPainter."""
        current_index = 0
        if self.current_image_path in self.loaded_image_order:
            current_index = self.loaded_image_order.index(self.current_image_path) + 1

        legend_text = (
            "Shortcuts: S=Save  L=Load  E=Edit Label  Del/Backspace/D=Delete  H=Hide/Show\n"
            f"Image: {current_index}/{len(self.loaded_image_order)}  Boxes: {len(self.boxes)}"
        )

        font = QFont("Arial", 10)
        painter.setFont(font)
        metrics = QFontMetrics(font)

        lines = legend_text.split("\n")
        max_w = max(metrics.horizontalAdvance(line) for line in lines)
        line_h = metrics.height()

        pad = 6
        x, y = 10, 10
        total_h = line_h * len(lines)

        bg_rect = QRect(x - pad, y - pad, max_w + pad * 2, total_h + pad * 2)
        painter.fillRect(bg_rect, QColor(0, 0, 0))
        painter.setPen(QPen(QColor("#666666"), 1))
        painter.drawRect(bg_rect)

        painter.setPen(QColor("white"))
        for i, line in enumerate(lines):
            painter.drawText(x, y + metrics.ascent() + i * line_h, line)

    def draw_legend(self):
        """Alias kept for API compatibility; triggers a full canvas repaint."""
        self.redraw_overlays()

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

            image_size = record.get("image_size") or {}
            width = image_size.get("width")
            height = image_size.get("height")
            if width is None or height is None:
                width, height = cls.get_image_size(image_path)

            image_records.append({
                "image": image_path,
                "image_size": {"width": int(width), "height": int(height)},
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

    def get_default_annotated_image_path(self):
        image_dir = self.get_dirname(self.image_path) or "."
        image_name = os.path.splitext(self.get_basename(self.image_path))[0]
        return self.join_path(image_dir, f"{image_name}_annotated.png")

    @staticmethod
    def get_image_format_from_path(path):
        extension = os.path.splitext(str(path))[1].lower()
        return {
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".png": "PNG",
            ".bmp": "BMP",
            ".gif": "GIF",
            ".tif": "TIFF",
            ".tiff": "TIFF",
        }.get(extension, "PNG")

    def choose_output_annotated_image_path(self):
        initial_path = self.get_default_annotated_image_path()

        dialog_initialdir = os.path.dirname(self.SETTINGS_FILE) or "."
        if self.image_path and not self.is_s3_path(self.image_path):
            dialog_initialdir = self.get_dirname(self.image_path) or dialog_initialdir

        dialog_initialfile = self.get_basename(initial_path) or "annotated_image.png"

        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export annotated image",
            os.path.join(dialog_initialdir, dialog_initialfile),
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;Bitmap image (*.bmp)"
            ";;TIFF image (*.tif *.tiff);;GIF image (*.gif);;All files (*.*)",
        )
        if selected_path:
            return self.normalize_path(selected_path)
        return None

    def choose_output_json_path(self):
        initial_path = self.output_json or self.get_default_output_path()

        dialog_initialdir = os.path.dirname(self.SETTINGS_FILE) or "."
        if self.image_path and not self.is_s3_path(self.image_path):
            dialog_initialdir = self.get_dirname(self.image_path) or dialog_initialdir

        if initial_path and not self.is_s3_path(initial_path):
            dialog_initialdir = self.get_dirname(initial_path) or dialog_initialdir

        dialog_initialfile = self.get_basename(initial_path) or "annotations.jsonl"

        selected_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save bounding boxes JSON Lines",
            os.path.join(dialog_initialdir, dialog_initialfile),
            "JSON Lines files (*.jsonl);;All files (*.*)",
        )
        if selected_path:
            self.output_json = self.normalize_path(selected_path)
            return True
        return False

    def load_boxes_json(self, json_path=None):
        if not json_path:
            json_path, _ = QFileDialog.getOpenFileName(
                self,
                "Open bounding boxes JSON Lines",
                "",
                "JSON Lines files (*.jsonl);;All files (*.*)",
            )
            if not json_path:
                return False

        json_path = self.normalize_path(json_path)
        image_records, selected_image_path = self.read_annotation_file(json_path, parent=self)
        self.set_loaded_records(
            image_records,
            selected_image_path=selected_image_path,
            output_json=json_path,
            prompt_selection=False,
        )
        return True

    def load_boxes_json_event(self, _event=None):
        try:
            if self.load_boxes_json():
                QMessageBox.information(
                    self,
                    "Loaded",
                    f"Loaded {len(self.loaded_image_order)} image(s) from {self.output_json}",
                )
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))

    def open_image_event(self):
        image_paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open image files",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.gif *.tiff);;All files (*.*)",
        )
        if not image_paths:
            return

        try:
            self.open_paths(image_paths)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))

    def open_folder_event(self):
        folder_path = QFileDialog.getExistingDirectory(self, "Open folder of images")
        if not folder_path:
            return

        try:
            image_paths = self.list_image_paths_in_folder(folder_path)
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))
            return

        if not image_paths:
            QMessageBox.information(
                self,
                "No Images Found",
                "No supported image files were found in the selected folder.",
            )
            return

        try:
            self.set_loaded_image_paths(
                image_paths, output_json=None, prompt_selection=len(image_paths) > 1
            )
        except Exception as exc:
            QMessageBox.critical(self, "Load Error", str(exc))

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

        reply = QMessageBox.question(
            self,
            "Delete Box",
            confirm_message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.boxes.pop(self.selected_box_index)
        self.selected_box_index = None
        self.sync_current_image_record()
        self.refresh_image_list(select_path=self.current_image_path)
        self.refresh_label_list(select_index=None)
        self.redraw_overlays()
        self.maybe_autosave()

    def save_boxes_json(self, prompt_for_path=False):
        if not self.loaded_image_order:
            raise ValueError("No images are loaded. Open an image or folder before saving annotations.")

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
                QMessageBox.critical(self, "Save Error", f"Could not update annotation file:\n{exc}")
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
        self.mark_annotation_state_saved()
        return True

    def save_boxes_json_event(self, _event=None):
        try:
            if self.save_boxes_json(prompt_for_path=True):
                QMessageBox.information(self, "Saved", f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def save_boxes_json_to_path_event(self):
        try:
            if self.choose_output_json_path_from_prompt() and self.save_boxes_json(prompt_for_path=False):
                QMessageBox.information(self, "Saved", f"Saved annotations for {len(self.loaded_image_order)} image(s) to {self.output_json}")
        except Exception as exc:
            QMessageBox.critical(self, "Save Error", str(exc))

    def save_annotated_image(self, output_path=None, prompt_for_path=True):
        if self.current_image_path is None or self.original_image is None:
            raise ValueError("No image is currently displayed.")

        if prompt_for_path or not output_path:
            output_path = self.choose_output_annotated_image_path()
            if not output_path:
                print("Export cancelled.")
                return False

        output_path = self.normalize_path(output_path)
        self.sync_current_image_record()

        annotated_image = self.original_image.copy()
        image_format = self.get_image_format_from_path(output_path)
        if image_format == "JPEG" and annotated_image.mode != "RGB":
            annotated_image = annotated_image.convert("RGB")

        draw = ImageDraw.Draw(annotated_image)
        export_font_size, line_width, text_padding = self.get_export_annotation_style()
        font = self.load_annotation_font(export_font_size)

        for index, box in enumerate(self.boxes, start=1):
            x1 = int(box["x1"])
            y1 = int(box["y1"])
            x2 = int(box["x2"])
            y2 = int(box["y2"])
            label_text = str(box.get("label", "")).strip() or f"box_{index}"

            draw.rectangle([x1, y1, x2, y2], outline="red", width=line_width)

            text_bbox = self.get_text_bbox(draw, label_text, font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]

            text_x = x1 + line_width
            text_y = max(0, y1 - text_h - (text_padding * 2) - line_width)

            draw.rectangle(
                [text_x, text_y, text_x + text_w + (text_padding * 2), text_y + text_h + (text_padding * 2)],
                fill="red"
            )
            draw.text(
                (text_x + text_padding, text_y + text_padding),
                label_text,
                fill="white",
                font=font,
            )

        with self.open_path(output_path, "wb") as f:
            annotated_image.save(f, format=image_format)

        self.last_exported_image_path = output_path
        print(f"Saved annotated image to {output_path}")
        return True

    def save_annotated_image_event(self, _event=None):
        try:
            if self.save_annotated_image(prompt_for_path=True):
                QMessageBox.information(
                    self, "Saved", f"Saved annotated image to {self.last_exported_image_path}"
                )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def clear_boxes_event(self, _event=None):
        if not self.boxes:
            return
        reply = QMessageBox.question(
            self,
            "Clear Boxes",
            "Clear all bounding boxes for the current image?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
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
        """Called by the Exit menu action."""
        self.close()


if __name__ == "__main__":
    try:
        ImageBboxSelector()
    except Exception as exc:
        _app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Startup Error", str(exc))
        sys.exit(1)
