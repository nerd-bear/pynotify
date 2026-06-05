"""
PyNotify -> A lightweight, single file notification library for Windows.
Provides modern Windows toasts, legacy Win32 balloon tips, system alerts, and PNCN (Py Notify Custom Notifications).
"""

import sys
# even though the PNCN *can* be cross platform,
# the main lib relies heavily on the pywin32 API, 
# so it just blocks import on unsupported OSes.
if sys.platform != "win32":
    raise ImportError(
        f"Unsupported OS: {sys.platform}. PyNotify only works on Windows.")

import os
import time
import threading
import queue
from pathlib import Path
from enum import Enum, IntEnum
from typing import Callable, Optional, Union, List, Dict, Any
import tkinter as tk

import winsound
import win32gui
import win32con

from windows_toasts import (
    Toast,
    WindowsToaster,
    InteractableWindowsToaster,
    ToastAudio,
    AudioSource,
    ToastButton,
    ToastDisplayImage
)

__all__ = ["PyNotify", "ToastType", "BalloonType", "AlertType", "NotifType"]


class ToastType(IntEnum):
    """Enumeration for modern Windows Toast audio types."""
    DEFAULT = 0
    IM = 1
    REMINDER = 2
    SILENT = 3


class BalloonType(IntEnum):
    """Enumeration for legacy Win32 Balloon notification icons."""
    INFO = 0
    ERROR = 1
    WARNING = 2
    NONE = 3


class AlertType(IntEnum):
    """Enumeration for system alert sounds."""
    ASTERISK = 0
    HAND = 1
    EXCLAMATION = 2
    BEEP = 3
    CUSTOM = 4


class NotifType(Enum):
    """
    Enumeration for custom Tkinter notification themes.
    To create more themes, you can use the add_notiftype/remove_notiftype methods on the PyNotify class.
    Each theme requires a background color (bg), an accent color for highlights (accent), and a text color (fg).
    """
    INFO = {"bg": "#2f3136", "accent": "#7289da", "fg": "#ffffff"}
    SUCCESS = {"bg": "#2f3136", "accent": "#43b581", "fg": "#ffffff"}
    WARNING = {"bg": "#2f3136", "accent": "#faa61a", "fg": "#ffffff"}
    ERROR = {"bg": "#2f3136", "accent": "#f04747", "fg": "#ffffff"}


def add_notiftype(name: str, bg: str, accent: str, fg: str) -> None:
    """
    Dynamically add a new notification type to the NotifType enum.

    Parameters
    ----------
    name : str
        The name of the new notification type (e.g., "ALERT").
    bg : str
        Background color in hex format (e.g., "#2f3136").
    accent : str
        Accent color for highlights in hex format (e.g., "#7289da").
    fg : str
        Text color in hex format (e.g., "#ffffff").
    """
    if hasattr(NotifType, name):
        raise ValueError(f"Notification type '{name}' already exists.")

    NotifType._member_map_[name] = NotifType(
        {"bg": bg, "accent": accent, "fg": fg})


def remove_notiftype(name: str) -> None:
    """
    Dynamically remove a notification type from the NotifType enum.

    Parameters
    ----------
    name : str
        The name of the notification type to remove (e.g., "ALERT").
    """
    if not hasattr(NotifType, name):
        raise ValueError(f"Notification type '{name}' does not exist.")

    del NotifType._member_map_[name]


class _NotificationUI(tk.Toplevel):
    """Internal class representing the visual window for a custom Tkinter notification."""

    def __init__(
        self,
        master: tk.Tk,
        title: str,
        message: str,
        notif_type: NotifType,
        duration: float,
        buttons: Optional[List[Dict[str, Any]]],
        y_offset: int
    ):
        super().__init__(master)

        self.duration_ms = int(duration * 1000)
        self.time_left = self.duration_ms
        self.theme = notif_type.value

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.config(bg=self.theme["bg"])

        self.width = 340
        self.height = 100 + (35 if buttons else 0)
        self.screen_width = self.winfo_screenwidth()
        self.screen_height = self.winfo_screenheight()

        # bellow screen
        self.x_pos = self.screen_width - self.width - 20
        self.target_y = self.screen_height - 60 - self.height - y_offset
        self.current_y = self.screen_height
        self.geometry(
            f"{self.width}x{self.height}+{self.x_pos}+{self.current_y}")

        self._build_ui(title, message, buttons)

        self.after(10, self._slide_in)
        if self.duration_ms > 0:
            self.after(50, self._update_timer)

    def _build_ui(self, title: str, message: str, buttons: Optional[List[Dict[str, Any]]]) -> None:
        """Constructs the modern grid layout."""
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)

        accent = tk.Frame(self, bg=self.theme["accent"], width=6)
        accent.grid(row=0, column=0, rowspan=4, sticky="ns")

        title_lbl = tk.Label(
            self, text=title, bg=self.theme["bg"], fg=self.theme["fg"],
            font=("Segoe UI", 11, "bold"), anchor="w"
        )
        title_lbl.grid(row=0, column=1, sticky="ew", padx=10, pady=(10, 0))

        close_btn = tk.Label(
            self, text="✕", bg=self.theme["bg"], fg="#7a7c80",
            font=("Segoe UI", 10, "bold"), cursor="hand2"
        )
        close_btn.grid(row=0, column=2, sticky="ne", padx=10, pady=(10, 0))
        close_btn.bind("<Button-1>", lambda e: self._fade_out())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#dcddde"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#7a7c80"))

        msg_lbl = tk.Label(
            self, text=message, bg=self.theme["bg"], fg="#dcddde",
            font=("Segoe UI", 10), justify="left", wraplength=self.width - 40
        )
        msg_lbl.grid(row=1, column=1, columnspan=2,
                     sticky="nw", padx=10, pady=(5, 10))

        if buttons:
            btn_frame = tk.Frame(self, bg=self.theme["bg"])
            btn_frame.grid(row=2, column=1, columnspan=2,
                           sticky="ew", padx=10, pady=(0, 10))

            for btn in buttons:
                b = tk.Label(
                    btn_frame, text=btn.get("text", "Action"), bg="#4f545c",
                    fg=self.theme["fg"], font=("Segoe UI", 9, "bold"),
                    cursor="hand2", padx=15, pady=5
                )
                b.pack(side="right", padx=(10, 0))

                b.bind("<Enter>", lambda e, w=b: w.config(bg="#686d73"))
                b.bind("<Leave>", lambda e, w=b: w.config(bg="#4f545c"))
                b.bind("<Button-1>", lambda e, c=btn.get("on_click",
                       lambda: None): self._execute_and_close(c))

        if self.duration_ms > 0:
            self.progress_bg = tk.Frame(self, bg="#202225", height=4)
            self.progress_bg.grid(row=3, column=1, columnspan=2, sticky="ew")

            self.progress_bar = tk.Frame(
                self.progress_bg, bg=self.theme["accent"], height=4)
            self.progress_bar.place(x=0, y=0, relwidth=1.0)

    def _execute_and_close(self, callback: Callable) -> None:
        """Runs the button action and dismisses the toast."""
        callback()
        self._fade_out()

    def _slide_in(self) -> None:
        """Animates the window sliding up into view."""
        if self.current_y > self.target_y:
            speed = max(2, int((self.current_y - self.target_y) * 0.2))
            self.current_y -= speed
            self.geometry(f"+{self.x_pos}+{self.current_y}")
            self.after(16, self._slide_in)

    def _update_timer(self) -> None:
        """Shrinks the progress bar over time and triggers fade out."""
        self.time_left -= 50
        if self.time_left <= 0:
            self._fade_out()
        else:
            pct = max(0.0, self.time_left / self.duration_ms)
            self.progress_bar.place(relwidth=pct)
            self.after(50, self._update_timer)

    def _fade_out(self, alpha: float = 1.0) -> None:
        """Fades the window out cleanly before destroying it."""
        alpha -= 0.08
        if alpha > 0:
            self.attributes("-alpha", alpha)
            self.after(16, lambda: self._fade_out(alpha))
        else:
            self.destroy()


class PyNotify:
    """
    A unified interface for dispatching Windows notifications and alerts.
    """

    def __init__(self, app_id: str = "PyNotify App", app_icon: Optional[Union[str, os.PathLike]] = None):
        """
        Initialize the notification service.

        Parameters
        ----------
        app_id : str
            The application identifier displayed on modern toasts.
        app_icon : str | PathLike | None
            The global fallback icon path (.png/.jpg for toasts, .ico for balloons).
        """
        self.app_id = app_id
        self.app_icon = app_icon

        # PNCNS queue/daemon thread
        self._custom_queue = queue.Queue()
        self._active_custom_toasts = []
        self._ui_thread = threading.Thread(
            target=self._run_ui_loop, daemon=True)
        self._ui_thread.start()

    def _run_ui_loop(self) -> None:
        """The isolated Tkinter environment for custom notifications."""
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.after(100, self._process_queue)
        self.root.mainloop()

    def _process_queue(self) -> None:
        """Checks if the main Python thread asked for a new custom notification."""
        try:
            while True:
                task = self._custom_queue.get_nowait()
                self._spawn_custom_toast(task)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_queue)

    def _spawn_custom_toast(self, data: Dict[str, Any]) -> None:
        """Creates and tracks a new Tkinter notification on the screen."""
        self._active_custom_toasts = [
            t for t in self._active_custom_toasts if t.winfo_exists()]

        # stacking offset dynamically
        y_offset = sum(t.height + 15 for t in self._active_custom_toasts)

        toast = _NotificationUI(
            master=self.root,
            title=data["title"],
            message=data["message"],
            notif_type=data["notif_type"],
            duration=data["duration"],
            buttons=data["buttons"],
            y_offset=y_offset
        )
        self._active_custom_toasts.append(toast)

    def toast(
        self,
        title: str,
        message: str,
        toast_type: ToastType = ToastType.DEFAULT,
        *,
        icon_path: Optional[Union[str, os.PathLike]] = None,
        on_click: Optional[Callable] = None,
        buttons: Optional[List[dict]] = None
    ) -> None:
        """
        Dispatch a modern Windows 10/11 toast notification.
        """
        audio_sources = {
            ToastType.DEFAULT: ToastAudio(sound=AudioSource.Default),
            ToastType.IM: ToastAudio(sound=AudioSource.IM),
            ToastType.REMINDER: ToastAudio(sound=AudioSource.Reminder),
            ToastType.SILENT: ToastAudio(silent=True),
        }

        if toast_type not in audio_sources:
            raise ValueError(f"Unknown toast type: {toast_type}")

        if on_click or buttons:
            toaster = InteractableWindowsToaster(self.app_id)
        else:
            toaster = WindowsToaster(self.app_id)

        toast = Toast()
        toast.text_fields = [title, message]
        toast.audio = audio_sources[toast_type]

        target_icon = icon_path or getattr(self, "app_icon", None)
        if target_icon:
            path_obj = Path(target_icon)
            if not path_obj.is_file():
                raise FileNotFoundError(f"Icon file not found: {target_icon}")
            toast.AddImage(ToastDisplayImage.fromPath(str(path_obj)))

        if on_click:
            toast.on_activated = lambda _: on_click()

        if buttons:
            for i, btn in enumerate(buttons):
                action = ToastButton(btn.get("text", f"Button {i+1}"), str(i))
                action.on_activated = lambda _, c_btn=btn: c_btn.get(
                    "on_click", lambda: None)()
                toast.AddAction(action)

        toaster.show_toast(toast)

    def schedule_toast(self, delay: float, **kwargs) -> threading.Timer:
        """
        Schedule a toast notification to appear after a delay.
        """
        timer = threading.Timer(delay, self.toast, kwargs=kwargs)
        timer.daemon = True
        timer.start()
        return timer

    def custom_toast(
        self,
        title: str,
        message: str,
        notif_type: NotifType = NotifType.INFO,
        *,
        duration: float = 5.0,
        buttons: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """
        Dispatch a custom PyNotify Tkinter Notification (PNCNS).

        Parameters
        ----------
        title : str
            Title of the notification.
        message : str
            Body text of the notification.
        notif_type : NotifType
            Visual theme for the notification (INFO, SUCCESS, WARNING, ERROR).
        duration : float
            Duration in seconds before the notification fades out.
        buttons : list of dict, optional
            List of dictionaries containing 'text' and 'on_click' callables.
        """
        self._custom_queue.put({
            "title": title,
            "message": message,
            "notif_type": notif_type,
            "duration": duration,
            "buttons": buttons
        })

    def balloon(
        self,
        title: str,
        message: str,
        balloon_type: BalloonType = BalloonType.INFO,
        *,
        duration: float = 2.5
    ) -> None:
        """
        Dispatch a legacy Win32 balloon notification in a non-blocking thread.
        """
        if duration <= 0:
            raise ValueError("Duration must be greater than 0 seconds.")

        thread = threading.Thread(
            target=self._show_balloon_blocking,
            args=(title, message, balloon_type, duration),
            daemon=True
        )
        thread.start()

    def _show_balloon_blocking(
        self,
        title: str,
        message: str,
        balloon_type: BalloonType,
        duration: float
    ) -> None:
        """Internal blocking method for the Win32 balloon API."""
        info_flags = {
            BalloonType.INFO: win32gui.NIIF_INFO,
            BalloonType.ERROR: win32gui.NIIF_ERROR,
            BalloonType.WARNING: win32gui.NIIF_WARNING,
            BalloonType.NONE: win32gui.NIIF_NONE,
        }

        flag = info_flags.get(balloon_type, win32gui.NIIF_INFO)
        wc = win32gui.WNDCLASS()
        hinst = wc.hInstance = win32gui.GetModuleHandle(None)

        wc.lpszClassName = f"PythonBalloon_{threading.get_native_id()}"
        wc.lpfnWndProc = {win32con.WM_DESTROY: lambda *args: 0}

        try:
            win32gui.RegisterClass(wc)
        except win32gui.error:
            pass

        hwnd = win32gui.CreateWindow(
            wc.lpszClassName, "Taskbar", win32con.WS_OVERLAPPED,
            0, 0, win32con.CW_USEDEFAULT, win32con.CW_USEDEFAULT,
            0, 0, hinst, None
        )

        hicon = win32gui.LoadIcon(0, win32con.IDI_INFORMATION)
        flags = win32gui.NIF_ICON | win32gui.NIF_MESSAGE | win32gui.NIF_TIP | win32gui.NIF_INFO
        nid = (hwnd, 0, flags, win32con.WM_USER + 20, hicon,
               self.app_id, message, 2000, title, flag)

        try:
            win32gui.Shell_NotifyIcon(win32gui.NIM_ADD, nid)
            time.sleep(duration)
        finally:
            win32gui.Shell_NotifyIcon(win32gui.NIM_DELETE, (hwnd, 0))
            win32gui.DestroyWindow(hwnd)
            try:
                win32gui.UnregisterClass(wc.lpszClassName, hinst)
            except win32gui.error:
                pass

    def play_sound(
        self,
        alert_type: AlertType = AlertType.ASTERISK,
        *,
        filepath: Optional[Union[str, os.PathLike]] = None,
        frequency: int = 800,
        duration: int = 500,
    ) -> None:
        """
        Play a system alert or custom WAV sound.
        """
        if alert_type == AlertType.ASTERISK:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

        elif alert_type == AlertType.HAND:
            winsound.MessageBeep(winsound.MB_ICONHAND)

        elif alert_type == AlertType.EXCLAMATION:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

        elif alert_type == AlertType.BEEP:
            if not (37 <= frequency <= 32767):
                raise ValueError("Frequency must be between 37 and 32767 Hz.")
            if duration <= 0:
                raise ValueError("Duration must be greater than 0 ms.")
            winsound.Beep(frequency, duration)

        elif alert_type == AlertType.CUSTOM:
            if not filepath:
                raise ValueError(
                    "A valid filepath must be provided for CUSTOM alerts.")

            path_obj = Path(filepath)
            if not path_obj.is_file() or path_obj.suffix.lower() != ".wav":
                raise ValueError(
                    f"Custom sound must be a valid .wav file: {filepath}")

            winsound.PlaySound(
                str(path_obj), winsound.SND_FILENAME | winsound.SND_ASYNC)

        else:
            raise ValueError(f"Unknown alert type: {alert_type}")


# test
if __name__ == "__main__":
    time.sleep(2)
    
    notifier = PyNotify(app_id="PyNotify Test")

    def background_task():
        print("Toast clicked callback")

    def btn_action():
        print("Action button clicked!")

    try:
        notifier.toast(
            title="Update Available",
            message="A new update is ready to install",
            toast_type=ToastType.REMINDER,
            on_click=background_task,
            buttons=[
                {"text": "Install", "on_click": btn_action},
                {"text": "Ignore", "on_click": lambda: print(
                    "Ignored.")}
            ]
        )
    except Exception as e:
        print(f"Native Toasts skipped: {e}")

    time.sleep(3)

    notifier.custom_toast(
        title="Custom Notification",
        message="This is a notification, belive it or not!",
        notif_type=NotifType.INFO,
        duration=6.0
    )
    time.sleep(3)

    notifier.custom_toast(
        title="System Error",
        message="This is a notification, belive it or not!",
        notif_type=NotifType.ERROR,
        duration=5.0,
        buttons=[
            {"text": "Dismiss", "on_click": lambda: print(
                "Error Ignored.")},
            {"text": "Details", "on_click": lambda: print(
                "Fetching details...")}
        ]
    )

    notifier.balloon(
        "Legacy Alert", "123", BalloonType.INFO)
    time.sleep(3)

    for i in range(1, 11):
        time.sleep(1)

    print("Demo complete")
