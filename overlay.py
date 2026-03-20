import tkinter as tk
import threading

overlay_window = None
_thread = None

def show_overlay():
    global overlay_window
    try:
        overlay_window = tk.Tk()
        overlay_window.title("")
        overlay_window.overrideredirect(True)
        overlay_window.configure(bg="#1a1a1a")
        overlay_window.attributes('-topmost', True)
        overlay_window.attributes('-alpha', 0.92)
        screen_w = overlay_window.winfo_screenwidth()
        screen_h = overlay_window.winfo_screenheight()
        overlay_window.geometry(f"170x55+{screen_w - 190}+{screen_h - 110}")
        tk.Label(
            overlay_window,
            text="  ⏺  Listening...",
            font=("Segoe UI", 13, "bold"),
            fg="#ff4444",
            bg="#1a1a1a"
        ).pack(expand=True)
        overlay_window.lift()
        overlay_window.mainloop()
    except Exception as e:
        print(f"Overlay error: {e}")

def hide_overlay():
    global overlay_window
    try:
        if overlay_window is not None:
            overlay_window.after(0, overlay_window.destroy)
    except Exception as e:
        print(f"Hide overlay error: {e}")
    finally:
        overlay_window = None

def start_overlay():
    global _thread
    _thread = threading.Thread(target=show_overlay, daemon=True)
    _thread.start()