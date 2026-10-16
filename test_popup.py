#!/usr/bin/env python3
"""
Standalone Test Target for Auto-Submit
Displays a window containing the Antigravity 'Submit' button so you can test
detection and clicking offline anytime.
"""

import sys
from pathlib import Path
import tkinter as tk
from PIL import Image, ImageTk

BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "submit_template.png"


def main():
    root = tk.Tk()
    root.title("Auto-Submit Test Target")
    root.geometry("340x180+400+300")
    root.configure(bg="#1e1e1e")
    root.attributes("-topmost", True)

    title_lbl = tk.Label(
        root,
        text="Auto-Submit Test Window",
        fg="#ffffff",
        bg="#1e1e1e",
        font=("Segoe UI", 11, "bold")
    )
    title_lbl.pack(pady=(12, 4))

    desc_lbl = tk.Label(
        root,
        text="The Auto-Submit tool should detect and click below:",
        fg="#999999",
        bg="#1e1e1e",
        font=("Segoe UI", 9)
    )
    desc_lbl.pack(pady=2)

    status_var = tk.StringVar(value="Status: Waiting for auto-click...")
    status_lbl = tk.Label(
        root,
        textvariable=status_var,
        fg="#aaaaaa",
        bg="#1e1e1e",
        font=("Segoe UI", 9, "bold")
    )

    img = Image.open(TEMPLATE_PATH)
    photo = ImageTk.PhotoImage(img)

    def on_btn_clicked(event=None):
        status_var.set("🎉 SUCCESS: Submit button was clicked!")
        status_lbl.configure(fg="#44ff44")
        root.configure(bg="#152b15")
        title_lbl.configure(bg="#152b15")
        desc_lbl.configure(bg="#152b15")
        status_lbl.configure(bg="#152b15")
        btn_widget.configure(bg="#152b15")

    btn_widget = tk.Label(root, image=photo, bg="#1e1e1e", cursor="hand2")
    btn_widget.image = photo
    btn_widget.pack(pady=8)
    btn_widget.bind("<Button-1>", on_btn_clicked)

    status_lbl.pack(pady=4)

    root.mainloop()


if __name__ == "__main__":
    main()
