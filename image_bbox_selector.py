import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageTk

class ImageBboxSelector:
    def __init__(self, image_path):
        self.root = tk.Tk()
        self.root.title("Image BBox Selector")
        
        self.image = Image.open(image_path)
        self.tk_image = ImageTk.PhotoImage(self.image)
        
        self.canvas = tk.Canvas(self.root, width=self.image.width, height=self.image.height)
        self.canvas.pack()
        
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_image)
        self.rect = None
        self.start_x = None
        self.start_y = None
        
        self.canvas.bind("<ButtonPress-1>", self.on_button_press)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_button_release)
        
        self.root.mainloop()

    def on_button_press(self, event):
        self.start_x = event.x
        self.start_y = event.y
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline='red')

    def on_mouse_drag(self, event):
        self.canvas.coords(self.rect, self.start_x, self.start_y, event.x, event.y)

    def on_button_release(self, event):
        end_x, end_y = event.x, event.y
        self.save_bbox(self.start_x, self.start_y, end_x, end_y)
        
    def save_bbox(self, start_x, start_y, end_x, end_y):
        bbox = (start_x, start_y, end_x, end_y)
        with open("bounding_box.txt", "w") as f:
            f.write(f"{bbox}\n")

if __name__ == "__main__":
    image_path = filedialog.askopenfilename()
    ImageBboxSelector(image_path)