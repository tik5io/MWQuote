"""
App icon utilities (load PNG assets and ICO files).
"""

from __future__ import annotations
import wx
import sys
from pathlib import Path


def get_app_root() -> Path:
    """Returns the root directory of the application, handling PyInstaller bundles."""
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def get_icon_path() -> Path:
    """Returns path to the main application .ico file."""
    return get_app_root() / "assets" / "app.ico"


def get_iconsheet_path() -> Path:
    """Returns path to the UI iconsheet."""
    return get_app_root() / "assets" / "ui_iconsheet.png"


def get_template_path() -> Path:
    """Returns path to the Excel template."""
    return get_app_root() / "assets" / "TEMPLATE.xlsx"


def get_bundled_config_path() -> Path:
    """Returns path to the bundled default configuration."""
    return get_app_root() / "assets" / "app_config.json"


def load_icon_from_sheet(index: int, icon_size: int = 160) -> wx.Bitmap:
    """
    Loads an icon from the iconsheet grid.
    Grid is assumed to be 4 columns wide.
    Sheet is 640x640, so icons are 160x160.
    
    0: Search    1: New       2: Save    3: Open
    4: Maint     5: Duplic    6: Delete  7: Export
    """
    sheet_path = get_iconsheet_path()
    path_str = str(sheet_path.absolute())
    if not sheet_path.exists():
        print(f"[DEBUG] Iconsheet not found at: {path_str}")
        return wx.NullBitmap
        
    img = wx.Image(path_str, wx.BITMAP_TYPE_ANY)
    if not img.IsOk():
        print(f"[DEBUG] wx.Image failed to load: {path_str}")
        return wx.NullBitmap
        
    cols = 4
    row = index // cols
    col = index % cols
    
    rect = wx.Rect(col * icon_size, row * icon_size, icon_size, icon_size)
    
    # Ensure rect is within image bounds
    if rect.x + rect.width > img.GetWidth() or rect.y + rect.height > img.GetHeight():
        print(f"[DEBUG] Icon rect {rect} out of bounds for image {img.GetSize()}")
        return wx.NullBitmap
        
    icon_img = img.GetSubImage(rect)
    return wx.Bitmap(icon_img)


def ensure_icon_file(size: int = 256) -> Path:
    """Ensures the app.ico exists (returns the path)."""
    path = get_icon_path()
    # Note: assets are now provided by the user, we just return the path
    return path
