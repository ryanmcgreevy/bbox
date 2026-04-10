import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk

class ImageBboxSelector:
    def __init__(self, image_path):
        self.root = tk.Tk()
        self.root.title("Image BBox Selector")

        self.original_image = Image.open(image_path)
        self.image = self.original_image.copy()
        self.tk_image = ImageTk.PhotoImage(self.image)

        self.canvas = tk.Canvas(self.root, width=self.image.width, height=self.image.height)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image, tags="image")
        self.rect = None
        self.start_x = None
        self.start_y = None

        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        self.canvas.bind("<Configure>", self.on_window_resize)

        self.root.mainloop()

    def on_window_resize(self, event):
        """Handle window resize events and scale the image accordingly"""
        if self.original_image and event.width > 0 and event.height > 0:
            resized_image = self.original_image.resize((event.width, event.height), Image.Resampling.LANCZOS)
            self.image = resized_image
            self.tk_image = ImageTk.PhotoImage(self.image)

            self.canvas.itemconfig("image", image=self.tk_image)
            self.canvas.coords("image", 0, 0)

            if self.rect:
                self.canvas.delete(self.rect)
                self.rect = None

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red', width=2)

    def on_mouse_drag(self, event):
        if self.rect:
            self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        self.save_bbox(self.start_x, self.start_y, end_x, end_y)

    def save_bbox(self, start_x, start_y, end_x, end_y):
        x1 = min(start_x, end_x)
        y1 = min(start_y, end_y)
        x2 = max(start_x, end_x)
        y2 = max(start_y, end_y)

        bbox = (x1, y1, x2, y2)
        with open("bounding_box.txt", "w") as f:
            f.write(f"{bbox}\n")
        print(f"Bounding box saved: {bbox}")

if __name__ == "__main__":
    image_path = filedialog.askopenfilename()
    if image_path:
        ImageBboxSelector(image_path)