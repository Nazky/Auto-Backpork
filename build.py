import PyInstaller.__main__
import os
import sys
import shutil
import subprocess
import urllib.request
import stat
from pathlib import Path

# =====================================================================
# CONFIGURATION
# =====================================================================
APP_NAME = "Auto-Backpork"
MAIN_SCRIPT = "gui.py"
BACKPORT_MODULE = "Backport.py"
SRC_FOLDER = "src"
ICON_FILE = "icon.png"

# =====================================================================
# HELPERS
# =====================================================================
def download_file(url, dest):
    print(f"Downloading {url}...")
    try:
        with urllib.request.urlopen(url) as response, open(dest, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IEXEC)
        return True
    except Exception as e:
        print(f"Error downloading {url}: {e}")
        return False

def create_dummy_icon(path):
    try:
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (256, 256), color=(70, 70, 70))
        d = ImageDraw.Draw(img)
        d.text((50, 100), "Icon", fill=(255, 255, 255))
        img.save(path)
        print(f"Created placeholder icon at {path}")
    except ImportError:
        pass

def get_src_hidden_imports():
    imports = []
    src_path = Path(SRC_FOLDER)
    if src_path.exists():
        for file in src_path.glob("*.py"):
            if file.name != "__init__.py":
                module_name = f"src.{file.stem}"
                imports.append("--hidden-import")
                imports.append(module_name)
    return imports

# =====================================================================
# BUILD FUNCTIONS
# =====================================================================

def build_windows():
    print("\n--- Building Windows Executable ---")
    icon_arg = ["--icon", ICON_FILE] if os.path.exists(ICON_FILE) else []

    args = [
        MAIN_SCRIPT, "--name", APP_NAME,
        "--noconsole", "--noconfirm", "--clean",
        "--add-data", f"{BACKPORT_MODULE}{os.pathsep}.",
        "--add-data", f"{SRC_FOLDER}{os.pathsep}{SRC_FOLDER}",
        "--collect-all", "customtkinter",
        "--collect-all", "Pillow",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "py7zr",
        "--hidden-import", "Backport",
        "--uac-admin",
    ] + icon_arg

    args.extend(get_src_hidden_imports())
    PyInstaller.__main__.run(args)
    print(f"\nSUCCESS! Windows build created in: dist{os.path.sep}{APP_NAME}")

def build_macos():
    print("\n--- Building macOS App Bundle ---")
    icon_arg = ["--icon", ICON_FILE] if os.path.exists(ICON_FILE) else []

    args = [
        MAIN_SCRIPT, "--name", APP_NAME,
        "--noconsole", "--noconfirm", "--clean",
        "--add-data", f"{BACKPORT_MODULE}{os.pathsep}.",
        "--add-data", f"{SRC_FOLDER}{os.pathsep}{SRC_FOLDER}",
        "--collect-all", "customtkinter",
        "--collect-all", "Pillow",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "py7zr",
        "--hidden-import", "Backport",
        "--windowed",
        "--osx-bundle-identifier", f"com.nazky.{APP_NAME.lower()}",
    ] + icon_arg

    args.extend(get_src_hidden_imports())
    PyInstaller.__main__.run(args)
    print(f"\nSUCCESS! macOS app created at: dist{os.path.sep}{APP_NAME}.app")

def build_linux_folder():
    """Builds the standard portable folder (basis for AppImage)."""
    print("\n--- Building Linux Portable Folder ---")
    args = [
        MAIN_SCRIPT, "--name", APP_NAME,
        "--noconsole", "--noconfirm", "--clean",
        "--add-data", f"{BACKPORT_MODULE}{os.pathsep}.",
        "--add-data", f"{SRC_FOLDER}{os.pathsep}{SRC_FOLDER}",
        "--collect-all", "customtkinter",
        "--collect-all", "Pillow",
        "--hidden-import", "PIL._tkinter_finder",
        "--hidden-import", "py7zr",
        "--hidden-import", "Backport",
    ]
    args.extend(get_src_hidden_imports())
    PyInstaller.__main__.run(args)
    print(f"\nSUCCESS! Portable folder created at: dist/{APP_NAME}")
    return Path("dist") / APP_NAME

def build_linux_appimage():
    print("\n--- Building Linux AppImage ---")
    
    # 1. Build the folder first
    dist_dir = build_linux_folder()
    if not dist_dir.exists():
        print("Error: Base build failed.")
        return

    # 2. Prepare AppDir Structure
    print("Preparing AppDir structure...")
    app_dir = Path("build") / "AppDir"
    if app_dir.exists(): shutil.rmtree(app_dir)
    
    usr_bin = app_dir / "usr" / "bin"
    usr_bin.mkdir(parents=True, exist_ok=True)

    # Copy PyInstaller output to AppDir
    print("Copying files to AppDir...")
    shutil.copytree(dist_dir, usr_bin, dirs_exist_ok=True)

    # --- FIX: Manually create AppRun script ---
    # This tells the AppImage exactly where the executable is.
    apprun_path = app_dir / "AppRun"
    apprun_content = """#!/bin/bash
# Auto-Backpork AppRun
# Get the directory where the AppImage is mounted
APPDIR="$(dirname "$(readlink -f "$0")")"

# Execute the binary located in usr/bin
exec "$APPDIR/usr/bin/Auto-Backpork" "$@"
"""
    apprun_path.write_text(apprun_content)
    apprun_path.chmod(0o755)
    print("Created custom AppRun script.")

    # Ensure the main binary is executable
    exe_path = usr_bin / APP_NAME
    if exe_path.exists():
        exe_path.chmod(0o755)

    # 3. Create Desktop Entry
    desktop_content = f"""[Desktop Entry]
Name={APP_NAME}
Exec=Auto-Backpork
Icon={APP_NAME}
Type=Application
Categories=Utility;
Terminal=false
"""
    (app_dir / f"{APP_NAME}.desktop").write_text(desktop_content)

    # 4. Handle Icon
    icon_dest = app_dir / f"{APP_NAME}.png"
    if os.path.exists(ICON_FILE):
        shutil.copy(ICON_FILE, icon_dest)
    else:
        create_dummy_icon(icon_dest)

    # 5. Download AppImageTool
    appimagetool_path = Path("build") / "appimagetool"
    appimagetool_url = "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    
    if not appimagetool_path.exists():
        if not download_file(appimagetool_url, appimagetool_path):
            print("Failed to download appimagetool. Cannot create AppImage.")
            return
    appimagetool_path.chmod(0o755)

    # 6. Build the AppImage
    print("Generating AppImage...")
    env = os.environ.copy()
    env["ARCH"] = "x86_64"
    output_appimage = Path("dist") / f"{APP_NAME}-x86_64.AppImage"
    
    cmd = [str(appimagetool_path.resolve()), str(app_dir.resolve()), str(output_appimage.resolve())]
    
    try:
        subprocess.run(cmd, check=True, env=env)
        print(f"\nSUCCESS! Linux AppImage created at: {output_appimage}")
    except subprocess.CalledProcessError:
        print("\n[ERROR] AppImage creation failed.")
        print("This is usually because 'libfuse2' is not installed on your build machine.")
        print("Run: sudo apt install libfuse2")
        print(f"However, the portable folder is still available at: {dist_dir}")

# =====================================================================
# MAIN
# =====================================================================
def main():
    # Pre-flight checks
    if not os.path.exists(MAIN_SCRIPT):
        print(f"Error: Main script '{MAIN_SCRIPT}' not found.")
        sys.exit(1)
    if not os.path.exists(SRC_FOLDER):
        print(f"Error: '{SRC_FOLDER}' folder not found.")
        sys.exit(1)
        
    # Ensure src has __init__.py
    init_file = Path(SRC_FOLDER) / "__init__.py"
    if not init_file.exists():
        print(f"Creating missing {init_file}...")
        init_file.touch()

    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller is not installed. Please run: pip install pyinstaller")
        sys.exit(1)

    print(f"Detected Platform: {sys.platform}")
    
    if sys.platform == "win32":
        build_windows()
        
    elif sys.platform == "darwin":
        build_macos()
        
    elif sys.platform == "linux":
        print("\nLinux Build Options:")
        print("1. Build AppImage (Requires libfuse2)")
        print("2. Build Portable Folder")
        
        choice = input("Select option (1-2): ").strip()
        
        if choice == "1":
            build_linux_appimage()
        elif choice == "2":
            build_linux_folder()
        else:
            print("Invalid choice.")
    else:
        print(f"Unsupported platform: {sys.platform}")

if __name__ == "__main__":
    main()