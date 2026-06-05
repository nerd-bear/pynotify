"""
PyNotify -> A lightweight, single file notification library for Windows.
Provides modern Windows toasts, legacy Win32 balloon tips, system alerts, and PNCN (Py Notify Custom Notifications).
"""

from .pynotify import (
    PyNotify,
    ToastType,
    BalloonType,
    AlertType,
    NotifType,
    add_notiftype,
    remove_notiftype,
)

__version__ = "0.0.5"

__all__ = [
    "PyNotify",
    "ToastType",
    "BalloonType",
    "AlertType",
    "NotifType",
    "add_notiftype",
    "remove_notiftype",
]