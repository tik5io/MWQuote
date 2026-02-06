import os
import shutil
from PIL import Image

def finalize_assets():
    os.makedirs("assets", exist_ok=True)
    
    # App Icon
    src_icon = "mwquote_app_icon_draft_1770306465765.png"
    if os.path.exists(src_icon):
        img = Image.open(src_icon)
        img.save("assets/app_icon.png")
        img.save("assets/app.ico", format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        print(f"App icon finalized from {src_icon}")
    
    # Iconsheet
    src_sheet = "mwquote_iconsheet_draft_1770306489436.png"
    if os.path.exists(src_sheet):
        shutil.copy2(src_sheet, "assets/ui_iconsheet.png")
        print(f"Iconsheet finalized from {src_sheet}")

if __name__ == "__main__":
    finalize_assets()
