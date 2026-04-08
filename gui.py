import os
import re
import json
import io
import time
import webbrowser
import platform
import subprocess
import zipfile
import tempfile
import threading
import base64
import shutil
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext

import py7zr
import rarfile
import customtkinter as ctk
from PIL import Image
import tkinter.filedialog as filedialog

# =====================================================================
# PYINSTALLER CONSOLE FIX (isatty error)
# =====================================================================
class DummyStream:
    """Fake stream for PyInstaller --noconsole mode to prevent isatty() crashes."""
    def write(self, text): pass
    def flush(self): pass
    def isatty(self): return False
    def fileno(self): return -1

# If running as a compiled GUI exe without a console, replace None streams
if getattr(sys, 'frozen', False) and (sys.stdout is None or sys.stderr is None):
    sys.stdout = DummyStream()
    sys.stderr = DummyStream()

# =====================================================================
# MACOS ENVIRONMENT FIX
# =====================================================================
def setup_macos_environment():
    """
    Fix PATH environment for macOS GUI apps.
    GUI apps on macOS do not inherit shell paths (like Homebrew /opt/homebrew/bin).
    We must manually add them so shutil.which() can find brew, unrar, 7z, etc.
    """
    if platform.system().lower() != "darwin":
        return

    # Common paths for Homebrew and standard binaries
    extra_paths = [
        "/opt/homebrew/bin",  # Apple Silicon Homebrew
        "/opt/homebrew/sbin",
        "/usr/local/bin",     # Intel Homebrew / Standard
        "/usr/local/sbin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
        "/opt/local/bin",     # MacPorts
    ]
    
    current_path = os.environ.get("PATH", "")
    paths = current_path.split(":")
    
    changed = False
    for p in extra_paths:
        if p not in paths:
            paths.append(p)
            changed = True
            
    if changed:
        os.environ["PATH"] = ":".join(paths)
        # print(f"[MACOS FIX] Updated PATH: {os.environ['PATH']}")

# Run this IMMEDIATELY before any other checks
setup_macos_environment()

def get_platform():
    """Get normalized platform name: 'windows', 'macos', or 'linux'."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    else:
        return "linux"


# Configure rarfile for cross-platform unrar
def configure_rarfile():
    """Configure rarfile to find unrar binary on different platforms."""
    current_platform = get_platform()
    if current_platform == "windows":
        # Windows: Find UnRAR.exe from WinRAR installation
        
        # Method 1: Check if unrar is in PATH
        unrar_path = shutil.which('unrar')
        if unrar_path:
            rarfile.UNRAR_TOOL = unrar_path
            return
        
        # Method 2: Check common WinRAR installation paths
        possible_paths = [
            r"C:\Program Files\WinRAR\UnRAR.exe",
            r"C:\Program Files (x86)\WinRAR\UnRAR.exe",
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                rarfile.UNRAR_TOOL = path
                # Add WinRAR directory to PATH so subprocess can find it
                winrar_dir = os.path.dirname(path)
                current_path = os.environ.get('PATH', '')
                if winrar_dir.lower() not in current_path.lower():
                    os.environ['PATH'] = current_path + ';' + winrar_dir
                return
        
        # Method 3: Check registry for WinRAR installation path
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\WinRAR archiver")
            install_location = winreg.QueryValueEx(key, "InstallLocation")[0]
            winreg.CloseKey(key)
            
            if install_location:
                unrar_exe = os.path.join(install_location, "UnRAR.exe")
                if os.path.exists(unrar_exe):
                    rarfile.UNRAR_TOOL = unrar_exe
                    os.environ['PATH'] = os.environ.get('PATH', '') + ';' + install_location
                    return
        except Exception:
            pass
        
        print("[RARFILE] WARNING: Could not find UnRAR on Windows!")
        
    elif current_platform == "macos":
        # Thanks to setup_macos_environment(), shutil.which should now work
        if shutil.which('unrar'):
            rarfile.UNRAR_TOOL = shutil.which('unrar')
            return
        if shutil.which('rar'):
            rarfile.UNRAR_TOOL = shutil.which('rar')
            return
            
        # Fallback hardcoded checks just in case
        possible_paths = [
            "/opt/homebrew/bin/unrar",
            "/usr/local/bin/unrar",
            "/usr/bin/unrar",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                rarfile.UNRAR_TOOL = path
                break
    else:  # Linux
        possible_paths = [
            "/usr/bin/unrar",
            "/usr/local/bin/unrar",
            "/usr/bin/unrar-free",
            "/snap/bin/unrar",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                rarfile.UNRAR_TOOL = path
                break

configure_rarfile()


# =====================================================================
# DEPENDENCY CHECKER & INSTALLER (Runs before GUI imports)
# =====================================================================
def check_and_install_dependencies():
    required_packages = {
        'customtkinter': 'customtkinter',
        'PIL': 'Pillow',
        'py7zr': 'py7zr',
        'rarfile': 'rarfile'
    }

    missing_packages = []
    for import_name, pip_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(pip_name)

    missing_system_tools = []
    
    if sys.platform == "win32":
        found_7z = shutil.which('7z') or any(Path(p).exists() for p in [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"])
        if not found_7z: missing_system_tools.append('7z')
        
        found_unrar = shutil.which('unrar') or any(Path(p).exists() for p in [r"C:\Program Files\WinRAR\UnRAR.exe", r"C:\Program Files (x86)\WinRAR\UnRAR.exe"])
        if not found_unrar: missing_system_tools.append('unrar')
    else:
        if not shutil.which('7z'): missing_system_tools.append('7z')
        if not shutil.which('unrar'): missing_system_tools.append('unrar')

    # =====================================================================
    # CRITICAL FIX: DETECT EXECUTABLE MODE
    # =====================================================================
    
    # If running as compiled executable (frozen), we CANNOT use pip install.
    # Attempting to run sys.executable would launch the app recursively (Fork Bomb).
    if getattr(sys, 'frozen', False):
        if missing_packages:
            # If python packages are missing in an exe, the build is broken.
            # Show error and exit immediately.
            root = tk.Tk()
            root.withdraw()
            missing_list = "\n".join(missing_packages)
            messagebox.showerror(
                "Critical Error", 
                f"The application is missing required internal libraries:\n\n{missing_list}\n\n"
                "This executable is corrupted. Please redownload or rebuild it."
            )
            sys.exit(1)
            
        if missing_system_tools:
            # We can warn, but we can't easily install system tools silently in app mode
            # without a package manager UI. We will just warn the user.
            root = tk.Tk()
            root.withdraw()
            messagebox.showwarning(
                "Missing Tools", 
                f"Missing system tools: {', '.join(missing_system_tools)}\n\n"
                "Some features (extraction) may not work.\n"
                "Please install them manually (e.g., 7-Zip, WinRAR/UnRAR)."
            )
        # If we reach here, critical checks passed.
        return True

    # =====================================================================
    # SCRIPT MODE (Development) - Allow Auto-Install
    # =====================================================================
    
    if not missing_packages and not missing_system_tools:
        return True

    setup_win = tk.Tk()
    setup_win.title("Auto-Backpork - Dependency Setup")
    setup_win.geometry("650x500")
    setup_win.configure(bg="#1a1a1a")

    tk.Label(setup_win, text="Setting up dependencies...", font=("Arial", 16, "bold"), bg="#1a1a1a", fg="white").pack(pady=10)
    log = scrolledtext.ScrolledText(setup_win, width=75, height=22, bg="#2b2b2b", fg="#00ff00", font=("Consolas", 10), state='normal')
    log.pack(padx=10, pady=5, fill="both", expand=True)

    def append_log(msg):
        log.insert(tk.END, msg + "\n")
        log.see(tk.END)
        setup_win.update()

    def install_pip(pkg_name):
        append_log(f"[PIP] Installing {pkg_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg_name, "--quiet", "--disable-pip-version-check"])
            append_log(f"[OK] {pkg_name} installed successfully.")
            return True
        except subprocess.CalledProcessError:
            append_log(f"[ERROR] Failed to install {pkg_name}.")
            return False

    def install_linux_tool(tool_name, package_managers):
        for pm_cmd, install_cmd, packages in package_managers:
            if shutil.which(pm_cmd):
                append_log(f"[SYSTEM] Found '{pm_cmd}'. Attempting to install {tool_name} ({packages[0]})...")
                try:
                    if pm_cmd not in ['nix-env', 'flatpak']:
                        if os.geteuid() != 0: cmd = ['sudo'] + install_cmd + packages
                        else: cmd = install_cmd + packages
                    else: cmd = install_cmd + packages
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    append_log(f"[OK] {tool_name} installed successfully via {pm_cmd}.")
                    return True
                except subprocess.CalledProcessError: append_log(f"[WARN] Installation failed via {pm_cmd}.")
                except FileNotFoundError: append_log(f"[WARN] '{pm_cmd.split()[0]}' command not found.")
        return False

    def install_system_tools():
        current_os = sys.platform
        tools_to_install = list(missing_system_tools)
        
        if '7z' in tools_to_install:
            append_log("\n[SYSTEM] '7z' binary not found.")
            installed = False
            if current_os == "win32":
                if shutil.which("winget"):
                    try:
                        subprocess.run(["winget", "install", "--id", "7zip.7zip", "--accept-source-agreements", "--accept-package-agreements", "--silent"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        append_log("[OK] 7-Zip installed."); tools_to_install.remove('7z'); installed = True
                    except Exception: append_log("[WARN] Winget failed.")
            elif current_os == "darwin":
                brew_path = shutil.which("brew") or "/opt/homebrew/bin/brew"
                if os.path.exists(brew_path):
                    try:
                        append_log(f"[SYSTEM] Found Homebrew at {brew_path}. Installing p7zip...")
                        subprocess.run([brew_path, "install", "p7zip"], check=True)
                        append_log("[OK] p7zip installed."); tools_to_install.remove('7z'); installed = True
                    except Exception as e: append_log(f"[ERROR] Homebrew failed: {e}")
            else:
                linux_pm = [('apt', ['apt', 'install', '-y'], ['p7zip-full']), ('dnf', ['dnf', 'install', '-y'], ['p7zip', 'p7zip-plugins']), ('pacman', ['pacman', '-S', '--noconfirm'], ['p7zip']), ('zypper', ['zypper', '--non-interactive', 'install'], ['p7zip-full']), ('apk', ['apk', 'add'], ['p7zip'])]
                if install_linux_tool('7z', linux_pm): tools_to_install.remove('7z'); installed = True
            if not installed: append_log("[WARN] Could not auto-install 7z.")

        if 'unrar' in tools_to_install:
            append_log("\n[SYSTEM] 'unrar' binary not found.")
            installed = False
            if current_os == "win32":
                if any(Path(p).exists() for p in [r"C:\Program Files\WinRAR\UnRAR.exe"]):
                    append_log("[OK] WinRAR found in C:\\Program Files\\WinRAR."); tools_to_install.remove('unrar'); installed = True
                elif shutil.which("winget"):
                    try:
                        subprocess.run(["winget", "install", "--id", "RARLab.WinRAR", "--accept-source-agreements", "--accept-package-agreements", "--silent"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        append_log("[OK] WinRAR installed."); tools_to_install.remove('unrar'); installed = True
                    except Exception: pass
            elif current_os == "darwin":
                brew_path = shutil.which("brew") or "/opt/homebrew/bin/brew"
                if os.path.exists(brew_path):
                    try:
                        subprocess.run([brew_path, "install", "unrar"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        append_log("[OK] unrar installed."); tools_to_install.remove('unrar'); installed = True
                    except Exception:
                        append_log("[WARN] Failed to install 'unrar'. Trying 'rar' as fallback...")
                        try:
                            subprocess.run([brew_path, "install", "rar"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                            append_log("[OK] 'rar' installed as fallback."); tools_to_install.remove('unrar'); installed = True
                        except Exception: append_log("[ERROR] Both 'unrar' and 'rar' failed via Homebrew.")
            else:
                linux_pm = [('apt', ['apt', 'install', '-y'], ['unrar']), ('dnf', ['dnf', 'install', '-y'], ['unrar']), ('pacman', ['pacman', '-S', '--noconfirm'], ['unrar']), ('zypper', ['zypper', '--non-interactive', 'install'], ['unrar']), ('apk', ['apk', 'add'], ['unrar'])]
                if install_linux_tool('unrar', linux_pm): tools_to_install.remove('unrar'); installed = True
            if not installed: append_log("[ERROR] Could not auto-install unrar. .rar extraction will FAIL.")

    setup_success = True
    def _run_setup():
        nonlocal setup_success
        setup_success = True
        for pkg in missing_packages:
            if not install_pip(pkg): setup_success = False
        if missing_system_tools: install_system_tools()

        append_log("\n--------------------------------------------------")
        if setup_success and not missing_system_tools:
            append_log("Setup complete! Launching GUI..."); setup_win.after(1500, setup_win.destroy)
        elif setup_success:
            append_log("Setup partially complete. Launching GUI..."); setup_win.after(4000, setup_win.destroy)
        else:
            append_log("CRITICAL ERRORS. Closing in 10s..."); setup_win.after(10000, setup_win.destroy); sys.exit(1)

    setup_win.after(100, _run_setup)
    setup_win.mainloop()
    return setup_success

if __name__ == "__main__":
    if not check_and_install_dependencies(): sys.exit(1)

# =====================================================================
# MAIN APP CLASS
# =====================================================================
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.platform = get_platform()
        
        # =====================================================================
        # ROBUST PATH HANDLING FOR EXECUTABLE & APPIMAGE
        # =====================================================================
        
        if getattr(sys, 'frozen', False):
            # Running as compiled executable (PyInstaller)
            bundle_path = Path(sys._MEIPASS)
            
            # Determine where to save user data (Config, Backport)
            # We want this to be WRITABLE.
            
            # 1. Check for Linux AppImage specifically
            # The APPIMAGE environment variable holds the path to the actual .AppImage file
            appimage_env = os.getenv('APPIMAGE')
            if self.platform == "linux" and appimage_env:
                # Data should be stored NEXT to the AppImage file
                application_path = Path(appimage_env).parent.resolve()
            
            # 2. Check for macOS .app bundle
            elif self.platform == "macos":
                # Data should be next to the .app bundle
                application_path = Path(sys.executable).parent.parent.parent.parent
            
            # 3. Standard Windows / Linux Portable Folder
            else:
                # Data is next to the executable
                application_path = Path(sys.executable).parent.resolve()
        else:
            # Running as script
            bundle_path = Path(__file__).parent.resolve()
            application_path = bundle_path

        self.project_root = application_path
        
        # 2. Setup Working Directories (Config, Backport)
        # These should be OUTSIDE the bundle (next to the exe/app) so they persist.
        self.config_base = self.project_root / "config"
        self.backport_dir = self.project_root / "Backport"
        
        self.title("Auto-Backpork GUI")
        self.geometry("1280x740")

        self.config_dir = self.config_base / "App"
        self.settings_file = self.config_dir / "settings.json"
        self.cache_file = self.config_dir / "games.json"
        
        # Create folders with permission fallback
        try:
            self.backport_dir.mkdir(parents=True, exist_ok=True)
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            # Fallback: If we can't write to the executable folder (Read-only AppImage or Permissions)
            # fall back to the user's home documents folder.
            print(f"Access denied at {self.project_root}: {e}")
            home = Path.home()
            self.project_root = home / "Auto-Backpork Data"
            self.backport_dir = self.project_root / "Backport"
            self.config_base = self.project_root / "config"
            self.config_dir = self.config_base / "App"
            
            self.backport_dir.mkdir(parents=True, exist_ok=True)
            self.config_dir.mkdir(parents=True, exist_ok=True)
            
            self.after(1000, lambda: messagebox.showwarning("Permission Notice", 
                f"Could not write to application folder.\nData is being saved to:\n{self.project_root}"))

        # 3. Setup PATH for Backport.py and SRC folder
        # When running as exe, these files are inside 'bundle_path' (sys._MEIPASS)
        # We add them to sys.path so 'import Backport' works and src is accessible.
        
        backport_file = bundle_path / "Backport.py"
        src_folder = bundle_path / "src"
        
        # Add paths to sys.path for imports
        if str(bundle_path) not in sys.path:
            sys.path.insert(0, str(bundle_path))
            
        if src_folder.exists() and str(src_folder) not in sys.path:
            sys.path.insert(0, str(src_folder))
            
        # Store src path reference if needed for direct file access
        self.src_path = src_folder if src_folder.exists() else (self.project_root / "src")

        # =====================================================================
        # STANDARD INITIALIZATION
        # =====================================================================

        # Changed: Now stores composite keys (source_path||internal_path) for deduplication
        self.seen_game_keys = set()
        self.seen_game_keys_lock = threading.Lock()
        self.game_widgets = {} 
        self.c_7z_binary = self._find_7z_binary()
        
        self.app_settings = self._load_app_settings()
        self.games_cache = self._load_games_cache()
        self._update_backport_dir()
        
        ctk.set_appearance_mode(self.app_settings.get("appearance_mode", "dark"))
        ctk.set_default_color_theme(self.app_settings.get("color_theme", "blue"))

        self.enable_7z_var = tk.BooleanVar(value=self.app_settings.get("enable_7z", False))
        self.appearance_mode_var = tk.StringVar(value=self.app_settings.get("appearance_mode", "dark"))
        self.color_theme_var = tk.StringVar(value=self.app_settings.get("color_theme", "blue"))
        self.max_scan_threads_var = tk.StringVar(value=str(self.app_settings.get("max_scan_threads", 4)))
        self.max_backport_threads_var = tk.StringVar(value=str(self.app_settings.get("max_backport_threads", 4)))
        self.view_mode_var = tk.StringVar(value=self.app_settings.get("view_mode", "List"))
        self.backport_semaphore = threading.Semaphore(int(self.max_backport_threads_var.get()))

        # Thread safety flag
        self.is_scanning = False

        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)

        self.main_tab = self.tabview.add("Main Page")
        self.settings_tab = self.tabview.add("Settings")

        self._setup_main_tab()
        self._setup_settings_tab()

        threading.Thread(target=self._periodic_sync_loop, daemon=True).start()
        self.after(100, self.load_from_cache_on_startup)

    def _sanitize_filename(self, name: str) -> str:
        """Remove invalid characters for Windows/Mac/Linux file systems."""
        if not name: return name
        invalid_chars = '<>:"/\\|?*\0'
        return "".join(c if c not in invalid_chars else '_' for c in name)

    def _update_backport_dir(self):
        custom_dir = self.app_settings.get("custom_output_dir", "")
        if custom_dir and os.path.isdir(custom_dir):
            self.backport_dir = Path(custom_dir)
        else:
            self.backport_dir = self.project_root / "Backport"
        self.backport_dir.mkdir(parents=True, exist_ok=True)

    def _setup_main_tab(self):
        self.instr_label = ctk.CTkLabel(self.main_tab, text="Select a folder to scan for games:", font=("Arial", 14))
        self.instr_label.pack(pady=(10, 5))

        self.scan_progress_frame = ctk.CTkFrame(self.main_tab, fg_color="transparent", height=20)
        self.scan_progress_bar = ctk.CTkProgressBar(self.scan_progress_frame, height=8, corner_radius=4)
        self.scan_progress_bar.pack(fill="x", padx=20, pady=(0, 5))
        self.scan_progress_bar.set(0)
        self.scan_progress_frame.pack_forget()

        btn_frame = ctk.CTkFrame(self.main_tab, fg_color="transparent")
        btn_frame.pack(pady=10)
        self.browse_btn = ctk.CTkButton(btn_frame, text="Choose a folder", command=self.browse_folder)
        self.browse_btn.pack(side="left", padx=5)
        self.refresh_btn = ctk.CTkButton(btn_frame, text="⟳", width=35, height=28, command=self.force_refresh_cache, fg_color="transparent", border_width=1, text_color="gray")
        self.refresh_btn.pack(side="left", padx=5)

        self.status_label = ctk.CTkLabel(self.main_tab, text="Ready.", text_color="gray")
        self.status_label.pack()

        bottom_frame = ctk.CTkFrame(self.main_tab, fg_color="transparent")
        bottom_frame.pack(side="bottom", pady=10) 
        self.backport_btn = ctk.CTkButton(bottom_frame, text="Start Backport All", fg_color="#8B5CF6", hover_color="#7C3AED", width=200, command=self.start_batch_backport)
        self.backport_btn.pack()

        self.scrollable_frame = ctk.CTkScrollableFrame(self.main_tab)
        self.scrollable_frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._setup_global_scroll()

    def _setup_settings_tab(self):
        settings_container = ctk.CTkFrame(self.settings_tab, fg_color="transparent")
        settings_container.pack(fill="both", expand=True)

        sidebar = ctk.CTkFrame(settings_container, width=150)
        sidebar.pack(side="left", fill="y", padx=(10, 5), pady=10)
        sidebar.pack_propagate(False)

        self.settings_content = ctk.CTkFrame(settings_container, fg_color="transparent")
        self.settings_content.pack(side="left", fill="both", expand=True, padx=(5, 10), pady=10)

        self.btn_general = ctk.CTkButton(sidebar, text="General", fg_color="transparent", text_color="gray", anchor="w", command=lambda: self.show_settings_page("general"))
        self.btn_backport = ctk.CTkButton(sidebar, text="Backport", fg_color="transparent", text_color="gray", anchor="w", command=lambda: self.show_settings_page("backport"))
        self.btn_credit = ctk.CTkButton(sidebar, text="Credit", fg_color="transparent", text_color="gray", anchor="w", command=lambda: self.show_settings_page("credit"))
        
        self.btn_general.pack(pady=10, padx=10, fill="x")
        self.btn_backport.pack(pady=10, padx=10, fill="x")
        self.btn_credit.pack(pady=10, padx=10, fill="x")

        # --- GENERAL PAGE ---
        self.page_general = ctk.CTkFrame(self.settings_content)
        ctk.CTkLabel(self.page_general, text="General Settings", font=("Arial", 20, "bold")).pack(pady=20)
        
        path_frame = ctk.CTkFrame(self.page_general, fg_color="transparent")
        path_frame.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(path_frame, text="Current Games Folder:", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        default_path = str(Path.home()) if self.platform != "windows" else "C:\\"
        self.path_var = tk.StringVar(value=self.app_settings.get("latest_folder", default_path))
        self.path_entry = ctk.CTkEntry(path_frame, textvariable=self.path_var, state="readonly")
        self.path_entry.grid(row=0, column=1, sticky="ew", padx=10, pady=5)
        path_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(path_frame, text="Change Folder", width=120, command=self.browse_folder).grid(row=0, column=2, padx=(10, 0))

        appearance_frame = ctk.CTkFrame(self.page_general, fg_color="transparent")
        appearance_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(appearance_frame, text="Appearance Mode:", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkOptionMenu(appearance_frame, variable=self.appearance_mode_var, values=["dark", "light", "system"], command=self._apply_appearance, width=150).grid(row=0, column=1, padx=10, pady=5)
        ctk.CTkLabel(appearance_frame, text="Color Theme:", font=("Arial", 14, "bold")).grid(row=1, column=0, sticky="w", pady=5)
        ctk.CTkOptionMenu(appearance_frame, variable=self.color_theme_var, values=["blue", "green", "dark-blue"], command=self._apply_color_theme, width=150).grid(row=1, column=1, padx=10, pady=5)

        view_frame = ctk.CTkFrame(self.page_general, fg_color="transparent")
        view_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(view_frame, text="Default View Mode:", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkSegmentedButton(view_frame, variable=self.view_mode_var, values=["List", "Grid"], command=self._rebuild_view, width=150).grid(row=0, column=1, padx=10, pady=5)

        ctk.CTkLabel(self.page_general, text="Performance & Multithreading", font=("Arial", 14, "bold")).pack(anchor="w", padx=20, pady=(20, 5))
        perf_frame = ctk.CTkFrame(self.page_general, fg_color="transparent")
        perf_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkLabel(perf_frame, text="Max Scan Threads:").grid(row=0, column=0, sticky="w", pady=5)
        ctk.CTkOptionMenu(perf_frame, variable=self.max_scan_threads_var, values=["1", "2", "4", "8"], width=150, command=lambda _: self._on_settings_changed()).grid(row=0, column=1, padx=10, pady=5)
        ctk.CTkLabel(perf_frame, text="Max Backport Threads:").grid(row=1, column=0, sticky="w", pady=5)
        ctk.CTkOptionMenu(perf_frame, variable=self.max_backport_threads_var, values=["1", "2", "4", "8"], width=150, command=self._apply_backport_threads).grid(row=1, column=1, padx=10, pady=5)
        
        ctk.CTkLabel(self.page_general, text=f"Platform: {self.platform.capitalize()} | Config: {self.config_base}", text_color="gray", font=("Arial", 10)).pack(anchor="w", padx=20, pady=(10, 0))

        # --- BACKPORT PAGE ---
        self.page_backport = ctk.CTkFrame(self.settings_content)
        ctk.CTkLabel(self.page_backport, text="Backport Settings", font=("Arial", 20, "bold")).pack(pady=(20, 10))
        
        output_frame = ctk.CTkFrame(self.page_backport, fg_color=("gray85", "gray20"), corner_radius=8)
        output_frame.pack(fill="x", padx=20, pady=(10, 15))
        ctk.CTkLabel(output_frame, text="Output Folder", font=("Arial", 14, "bold")).grid(row=0, column=0, sticky="w", padx=15, pady=(10, 5))
        self.output_path_var = tk.StringVar(value=str(self.backport_dir))
        self.output_path_entry = ctk.CTkEntry(output_frame, textvariable=self.output_path_var, state="readonly", width=350)
        self.output_path_entry.grid(row=1, column=0, sticky="ew", padx=15, pady=(0, 5))
        output_btn_frame = ctk.CTkFrame(output_frame, fg_color="transparent")
        output_btn_frame.grid(row=2, column=0, sticky="w", padx=15, pady=(0, 10))
        ctk.CTkButton(output_btn_frame, text="Choose Folder", width=120, command=self.browse_output_folder).pack(side="left", padx=(0, 5))
        ctk.CTkButton(output_btn_frame, text="Reset to Default", width=120, fg_color="transparent", border_width=1, text_color="gray", command=self.reset_output_folder).pack(side="left", padx=(0, 5))
        ctk.CTkButton(output_btn_frame, text="Open Folder", width=100, fg_color="transparent", border_width=1, text_color="gray", command=self.open_output_folder).pack(side="left")
        output_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.page_backport, text="If not set, defaults to the project's Backport folder.", text_color="gray", font=("Arial", 10)).pack(anchor="w", padx=20, pady=(0, 10))
        
        seven_z_status = f"7z binary: {'Found (' + self.c_7z_binary + ')' if self.c_7z_binary else 'Not found'}"
        ctk.CTkLabel(self.page_backport, text=seven_z_status, text_color="green" if self.c_7z_binary else "red", font=("Arial", 11)).pack(pady=(0, 10), padx=20, anchor="w")
        self.checkbox_7z = ctk.CTkCheckBox(self.page_backport, text="Enable 7z support (very slow on solid archives)", variable=self.enable_7z_var, command=self._on_7z_setting_changed)
        self.checkbox_7z.pack(pady=10, padx=20, anchor="w")

        ctk.CTkLabel(self.page_backport, text="Fakelib Scanner (Auto-sort by name):", font=("Arial", 14, "bold")).pack(pady=(20, 5), anchor="w", padx=20)
        fakelib_scan_frame = ctk.CTkFrame(self.page_backport, fg_color="transparent")
        fakelib_scan_frame.pack(fill="x", padx=20, pady=5)
        self.fakelib_scan_dir = tk.StringVar()
        self.fakelib_path_label = ctk.CTkLabel(fakelib_scan_frame, text="No file/folder selected", anchor="w", text_color="gray")
        self.fakelib_path_label.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        fakelib_scan_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(fakelib_scan_frame, text="From Folder", width=90, command=self.browse_fakelib_folder).grid(row=0, column=1, padx=(0, 5))
        ctk.CTkButton(fakelib_scan_frame, text="From Archive", width=90, fg_color="#1F6AA5", hover_color="#144870", command=self.browse_fakelib_archive).grid(row=0, column=2)
        fakelib_action_frame = ctk.CTkFrame(self.page_backport, fg_color="transparent")
        fakelib_action_frame.pack(fill="x", padx=20, pady=5)
        ctk.CTkButton(fakelib_action_frame, text="Scan & Sort Selected", width=200, fg_color="#8B5CF6", hover_color="#7C3AED", command=self.scan_and_organize_fakelib).pack(anchor="w")

        # --- CREDITS PAGE ---
        self.page_credit = ctk.CTkFrame(self.settings_content)
        ctk.CTkLabel(self.page_credit, text="Credits & Contributors", font=("Arial", 20, "bold")).pack(pady=20)
        credits_data = [
            ("Nazky (Creator)", [("Twitter", "https://x.com/NazkyYT"), ("Ko-fi", "https://ko-fi.com/nazkyyt"), ("Github", "https://github.com/Nazky")]),
            ("BestPig", [("Twitter", "https://x.com/bestpig"), ("Ko-fi", "https://ko-fi.com/bestpig"), ("Github", "https://github.com/BestPig")]),
            ("IdleSauce", [("Github", "https://github.com/idlesauce")]),
            ("john-tornblom", [("Github", "https://github.com/john-tornblom")]),
            ("EchoStretch", [("Github", "https://github.com/EchoStretch"), ("Twitter", "https://x.com/StretchEcho"), ("Ko-fi", "https://ko-fi.com/echostretch")])
        ]
        for name, links in credits_data:
            card_frame = ctk.CTkFrame(self.page_credit, fg_color=("gray85", "gray20"), corner_radius=8)
            card_frame.pack(fill="x", padx=20, pady=5)
            ctk.CTkLabel(card_frame, text=name, font=("Arial", 16, "bold")).pack(anchor="w", padx=15, pady=(10, 5))
            for platform_name, url in links:
                lbl = ctk.CTkLabel(card_frame, text=f"{platform_name}: {url}", font=("Arial", 12), text_color="#1E90FF", anchor="w", cursor="hand2")
                lbl.pack(anchor="w", padx=25, pady=1)
                lbl.bind("<Button-1>", lambda e, u=url: webbrowser.open(u))

        self.show_settings_page("general")

    # --- UI Helpers ---
    def show_settings_page(self, page_name):
        for page in [self.page_general, self.page_backport, self.page_credit]: page.pack_forget()
        for btn in [self.btn_general, self.btn_backport, self.btn_credit]: btn.configure(fg_color="transparent", text_color="gray")
        pages = {"general": (self.page_general, self.btn_general), "backport": (self.page_backport, self.btn_backport), "credit": (self.page_credit, self.btn_credit)}
        if page_name in pages:
            pages[page_name][0].pack(fill="both", expand=True)
            pages[page_name][1].configure(fg_color=("gray75", "gray30"), text_color="white")
            if page_name == "general": 
                self.path_var.set(self.app_settings.get("latest_folder", str(Path.home())))
            elif page_name == "backport": 
                self.output_path_var.set(str(self.backport_dir))

    
    def _setup_global_scroll(self):
        """Bind mousewheel globally so it works over any child widget."""
        if self.platform == "linux":
            self.bind_all("<Button-4>", self._on_mousewheel)
            self.bind_all("<Button-5>", self._on_mousewheel)
        else:
            self.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_mousewheel(self, event):
        """Handle mousewheel scroll only if the mouse is over the game list."""
        try:
            # Find the exact widget under the mouse cursor
            widget_under_mouse = self.winfo_containing(event.x_root, event.y_root)
            
            if widget_under_mouse is None:
                return
            
            # Check if the widget is inside our scrollable frame
            if not self._is_descendant_of(widget_under_mouse, self.scrollable_frame):
                return
            
            # Check if the widget is an interactive element (buttons, dropdowns, etc.)
            if self._is_interactive_widget(widget_under_mouse):
                return
            
            # Perform the scroll
            if self.platform == "linux":
                if event.num == 4:
                    self.scrollable_frame._parent_canvas.yview_scroll(-1, "units")
                elif event.num == 5:
                    self.scrollable_frame._parent_canvas.yview_scroll(1, "units")
            else:
                if self.platform == "windows":
                    units = -1 if event.delta > 0 else 1
                else:  # macOS
                    units = -event.delta
                self.scrollable_frame._parent_canvas.yview_scroll(units, "units")
                
        except Exception:
            # Prevent crashes if a widget is destroyed while scrolling
            pass

    def _is_descendant_of(self, widget, parent):
        """Check if a widget is a descendant of a specific parent widget."""
        current = widget
        while current is not None:
            if current == parent:
                return True
            current = current.master
        return False

    def _is_interactive_widget(self, widget):
        """Check if widget or any of its parents is an interactive CTk element."""
        interactive_types = {
            'CTkButton', 'CTkCheckBox', 'CTkOptionMenu', 
            'CTkSegmentedButton', 'CTkEntry', 'CTkSlider',
            'CTkSwitch', 'CTkRadioButton', 'CTkComboBox', 'CTkTextbox'
        }
        
        current = widget
        max_depth = 15  # Prevent infinite loops
        while current is not None and max_depth > 0:
            widget_type = type(current).__name__
            if widget_type in interactive_types:
                return True
            current = current.master
            max_depth -= 1
            
        return False

    def _find_7z_binary(self):
        # Thanks to the environment fix, shutil.which works reliably on macOS now
        binary = shutil.which('7z')
        if binary: return binary
        
        paths = { "windows": [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"], "macos": ["/opt/homebrew/bin/7z", "/usr/local/bin/7z"], "linux": ["/usr/bin/7z", "/usr/local/bin/7z", "/snap/bin/7z"] }.get(self.platform, [])
        for path in paths:
            if os.path.exists(path): return path
        return None

    def browse_output_folder(self):
        selected = filedialog.askdirectory(title="Select Output Folder", initialdir=str(self.backport_dir))
        if selected:
            self.app_settings["custom_output_dir"] = selected
            self._update_backport_dir()
            self.output_path_var.set(str(self.backport_dir))
            self._on_settings_changed()

    def reset_output_folder(self):
        self.app_settings["custom_output_dir"] = ""
        self._update_backport_dir()
        self.output_path_var.set(str(self.backport_dir))
        self._on_settings_changed()

    def open_output_folder(self):
        if not self.backport_dir.exists(): self.backport_dir.mkdir(parents=True, exist_ok=True)
        try:
            if self.platform == "windows": os.startfile(str(self.backport_dir))
            elif self.platform == "macos": subprocess.Popen(['open', str(self.backport_dir)])
            else: subprocess.Popen(['xdg-open', str(self.backport_dir)])
        except Exception as e: messagebox.showerror("Error", str(e))

    # --- Settings Management ---
    def _on_settings_changed(self):
        self.app_settings["enable_7z"] = self.enable_7z_var.get()
        self.app_settings["appearance_mode"] = self.appearance_mode_var.get()
        self.app_settings["color_theme"] = self.color_theme_var.get()
        try: self.app_settings["max_scan_threads"] = int(self.max_scan_threads_var.get()); self.app_settings["max_backport_threads"] = int(self.max_backport_threads_var.get())
        except: pass
        self.app_settings["view_mode"] = self.view_mode_var.get()
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f: json.dump(self.app_settings, f, indent=4)
        except: pass

    def _on_7z_setting_changed(self):
        self._on_settings_changed()

    def _apply_appearance(self, mode): ctk.set_appearance_mode(mode); self._on_settings_changed()
    def _apply_color_theme(self, theme): ctk.set_default_color_theme(theme); self._on_settings_changed()
    def _apply_backport_threads(self, val):
        try: self.backport_semaphore = threading.Semaphore(int(val))
        except: pass
        self._on_settings_changed()

    # --- Thread Safe UI Calls ---
    def _thread_safe_status(self, text, color): self.after(0, self.status_label.configure, {"text": text, "text_color": color})
    def _thread_safe_add(self, game_data, pil_image, source_type, source_path, internal_path=""): self.after(0, self.add_to_gui, game_data, pil_image, source_type, source_path, internal_path)
    def _thread_safe_btn_text(self, widget_key, text):
        info = self.game_widgets.get(widget_key)
        if info and info.get("btn_start"): self.after(0, info["btn_start"].configure, {"text": text})
    def _thread_safe_progress(self, widget_key, value):
        info = self.game_widgets.get(widget_key)
        if info and info.get("progress"): self.after(0, info["progress"].set, value)
    def _thread_safe_time(self, widget_key, text):
        info = self.game_widgets.get(widget_key)
        if info and info.get("time_label"): self.after(0, info["time_label"].configure, {"text": text})
    def _show_scan_progress(self): self.scan_progress_bar.set(0); self.after(0, lambda: self.scan_progress_frame.pack(before=self.instr_label, fill="x", pady=(0, 0)))
    def _hide_scan_progress(self): self.after(0, self.scan_progress_frame.pack_forget)
    def _update_scan_progress(self, value): self.after(0, self.scan_progress_bar.set, value)

    # --- View & Cache Management ---
    def _rebuild_view(self, value=None):
        self._on_settings_changed()
        mode = "grid" if self.view_mode_var.get() == "Grid" else "list"
        cols = 3 if mode == "grid" else 1
        for widget in self.scrollable_frame.winfo_children(): widget.destroy()
        self.scrollable_frame.grid_columnconfigure((0, 1, 2), weight=1) if mode == "grid" else [self.scrollable_frame.grid_columnconfigure(i, weight=0) for i in range(3)]
        for i, (widget_key, info) in enumerate(self.game_widgets.items()):
            row, col = i // cols, i % cols
            internal_path = info.get('internal_path', '')
            p, s, b, fv, fav, fm, t, pf = self.create_list_item(
                info["data"], info.get("pil_image"), info["source_type"], widget_key, 
                mode=mode, row=row, col=col, internal_path=internal_path
            )
            info.update({"progress": p, "status_label": s, "btn_start": b, "fakelib_var": fv, "fakelib_all_var": fav, "fakelib_menu": fm, "time_label": t, "progress_frame": pf})
            if info["is_processing"]:
                if mode == "list": info['progress_frame'].pack(side="bottom", fill="x", padx=10, pady=(0, 5))
                info['btn_start'].configure(text="Working...", state="disabled"); info['progress'].set(0.5)

    def get_available_fakelib_versions(self):
        versions = ["None"]
        if self.backport_dir.exists():
            found = [int(f.name.replace("fakelib-", "")) for f in self.backport_dir.iterdir() if f.is_dir() and f.name.startswith("fakelib-") and f.name.replace("fakelib-", "").isdigit()]
            versions.extend(str(v) for v in sorted(found))
        return versions

    def browse_fakelib_folder(self):
        p = filedialog.askdirectory(title="Select Fakelib Root Folder")
        if p: self.fakelib_path_label.configure(text=f"[Folder] {'...' + p[-42:] if len(p) > 45 else p}", text_color="white"); self.fakelib_scan_dir.set(p)

    def browse_fakelib_archive(self):
        p = filedialog.askopenfilename(title="Select Fakelib Archive", filetypes=[("Archives", "*.zip *.rar *.7z")])
        if p: self.fakelib_path_label.configure(text=f"[Archive] {Path(p).name}", text_color="white"); self.fakelib_scan_dir.set(p)

    def scan_and_organize_fakelib(self):
        import shutil
        scan_path = self.fakelib_scan_dir.get()
        if not scan_path or not os.path.exists(scan_path): 
            messagebox.showerror("Error", "Select a valid file/folder first."); 
            return
            
        valid_exts = ('.prx', '.sprx', '.self', '.bin', '.elf')
        is_archive = os.path.isfile(scan_path) and Path(scan_path).suffix.lower().lstrip('.') in ['zip', 'rar', '7z']
        copied = 0
        sdks = set()
        
        try:
            if is_archive:
                real_type = self.detect_real_archive_type(scan_path)
                if not real_type:
                    messagebox.showerror("Error", "Unsupported archive type or corrupt file.")
                    return
                
                with tempfile.TemporaryDirectory() as tmp:
                    try:
                        self._extract_all_archive_files(scan_path, real_type, tmp)
                    except Exception as e:
                        messagebox.showerror("Extraction Error", str(e))
                        return
                    
                    archive_root = tmp
                    tmp_path = Path(tmp)
                    top_level_items = list(tmp_path.iterdir())
                    if len(top_level_items) == 1 and top_level_items[0].is_dir():
                        archive_root = str(top_level_items[0])
                    
                    for root, dirs, files in os.walk(tmp):
                        sdk_det = self._get_sdk_from_path(root, archive_root)
                        
                        if sdk_det:
                            dest = self.backport_dir / f"fakelib-{sdk_det}"
                            dest.mkdir(parents=True, exist_ok=True)
                            sdks.add(sdk_det)
                            
                            for fn in files:
                                if fn.lower().endswith(valid_exts):
                                    src = os.path.join(root, fn)
                                    dst = dest / fn
                                    if not dst.exists():
                                        shutil.copy2(src, dst)
                                        copied += 1
                    
                    if not sdks:
                        has_files = any(
                            fn.lower().endswith(valid_exts) 
                            for r, _, files in os.walk(tmp) 
                            for fn in files
                        )
                        
                        if has_files:
                            det = self._extract_sdk_from_name(Path(scan_path).name)
                            if not det:
                                det = simpledialog.askstring("Fakelib SDK", "Found files, but no SDK folders.\nWhat FW/SDK should these go into? (e.g., 4, 7):", parent=self)
                            
                            if det:
                                dest = self.backport_dir / f"fakelib-{det}"
                                dest.mkdir(parents=True, exist_ok=True)
                                sdks.add(det)
                                
                                for r, _, f in os.walk(tmp):
                                    for fn in f:
                                        if fn.lower().endswith(valid_exts):
                                            src = os.path.join(r, fn)
                                            dst = dest / fn
                                            if not dst.exists():
                                                shutil.copy2(src, dst)
                                                copied += 1
                        else:
                            messagebox.showwarning("Wrong Files", f"Extracted files, but NONE of them end in {valid_exts}.")

            else:
                for root, dirs, files in os.walk(scan_path):
                    sdk_det = self._get_sdk_from_path(root, scan_path)
                    
                    if sdk_det:
                        dest = self.backport_dir / f"fakelib-{sdk_det}"
                        dest.mkdir(parents=True, exist_ok=True)
                        sdks.add(sdk_det)
                        
                        for fn in files:
                            if fn.lower().endswith(valid_exts):
                                src = os.path.join(root, fn)
                                dst = dest / fn
                                if not dst.exists():
                                    shutil.copy2(src, dst)
                                    copied += 1
                
                if not sdks:
                    has_files = any(
                        fn.lower().endswith(valid_exts) 
                        for r, _, files in os.walk(scan_path) 
                        for fn in files
                    )
                    if has_files:
                        det = simpledialog.askstring("SDK?", f"Found files, but no SDK folders. What FW/SDK for these files?")
                        if det:
                            dest = self.backport_dir / f"fakelib-{det}"
                            dest.mkdir(parents=True, exist_ok=True)
                            sdks.add(det)
                            for r, _, f in os.walk(scan_path):
                                for fn in f:
                                    if fn.lower().endswith(valid_exts):
                                        src = os.path.join(r, fn)
                                        dst = dest / fn
                                        if not dst.exists():
                                            shutil.copy2(src, dst)
                                            copied += 1
                    else:
                        messagebox.showwarning("Empty", "No valid fakelib files were found in the folder.")

            self._update_fakelib_dropdowns()
            
            if sdks:
                status_msg = f"Processed SDKs: {', '.join(sorted(sdks))}"
                if copied > 0:
                    status_msg += f"\nCopied {copied} new files."
                else:
                    status_msg += "\nAll files already exist (0 new files copied)."
                
                messagebox.showinfo("Done", status_msg)
                self.fakelib_path_label.configure(text=f"Done! (SDKs: {', '.join(sorted(sdks))})", text_color="#00FF00")
            else:
                self.fakelib_path_label.configure(text="No valid files found", text_color="#FFA500")
                
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _extract_sdk_from_name(self, name):
        m = re.search(r'(?:fakelib|sdk)[\s\-_]?(\d+(?:\.\d+)?)', name, re.IGNORECASE)
        return m.group(1).split('.')[0] if m else None
    
    def _get_sdk_from_path(self, current_root, base_root):
        try:
            rel_path = os.path.relpath(current_root, base_root)
            if rel_path == '.':
                return None
            parts = Path(rel_path).parts
            for part in parts:
                sdk = self._extract_sdk_from_name(part)
                if sdk:
                    return sdk
        except ValueError:
            pass
        return None

    def _update_fakelib_dropdowns(self):
        opts = self.get_available_fakelib_versions()
        for info in self.game_widgets.values():
            if info.get("fakelib_menu"):
                info["fakelib_menu"].configure(values=opts)
                if info["fakelib_var"].get() == "None" and len(opts) > 1: info["fakelib_var"].set(opts[1])

    # --- Core Backport Logic ---
    def start_single_backport(self, widget_key):
        info = self.game_widgets.get(widget_key)
        if not info or info.get('is_processing'): 
            return
            
        if not self.enable_7z_var.get() and ".7Z" in info.get('source_type', ""):
            info['status_label'].configure(text="Skipped (7z disabled)", text_color="#FFA500")
            return

        do_all_fakelib = info['fakelib_all_var'].get()
        selected_fakelib = info['fakelib_var'].get()
        
        if not do_all_fakelib and selected_fakelib == "None":
            continue_without = messagebox.askyesno(
                "No Fakelib Selected", 
                "Warning: You haven't selected a fakelib version.\nThe backport may not work correctly without one.\n\nDo you want to continue anyway?",
                icon='warning'
            )
            
            if not continue_without:
                return
            
            manual_sdk = simpledialog.askstring(
                "Input SDK Version", 
                "Since no fakelib is selected, please enter the target SDK version number:\n(e.g., 4, 7, 8)",
                parent=self
            )
            
            if not manual_sdk:
                return
            
            try:
                sdk_val = int(manual_sdk)
                if sdk_val <= 0:
                    messagebox.showerror("Invalid Input", "SDK version must be a positive number.")
                    return
                info['manual_sdk_override'] = sdk_val
            except ValueError:
                messagebox.showerror("Invalid Input", "Please enter a valid whole number for the SDK version.")
                return
        else:
            info['manual_sdk_override'] = None
        
        info['btn_start'].configure(text="Starting...", state="disabled")
        mode = "grid" if self.view_mode_var.get() == "Grid" else "list"
        if mode == "list": 
            info['progress_frame'].pack(side="bottom", fill="x", padx=10, pady=(0, 5))
        info['progress'].set(0.1)
        info['is_processing'] = True
        threading.Thread(target=self._backport_worker, args=(widget_key,), daemon=True).start()

    def start_batch_backport(self):
        for widget_key, info in self.game_widgets.items():
            if not info.get('is_processing') and not info["is_backported"]:
                info['fakelib_all_var'].set(True)
                self.start_single_backport(widget_key)

    def open_backport_folder(self, widget_key):
        info = self.game_widgets.get(widget_key)
        if not info: return
        data = info["data"]
        safe_title = self._sanitize_filename(data["titleName"])
        out_name = f"{safe_title} - {data['titleId']} - {data['contentVersion']}"
        fp = self.backport_dir / out_name
        if not fp.exists(): messagebox.showinfo("Not Found", f"No backport folder yet for:\n{data['titleName']}"); return
        try:
            if self.platform == "windows": os.startfile(str(fp))
            elif self.platform == "macos": subprocess.Popen(['open', str(fp)])
            else: subprocess.Popen(['xdg-open', str(fp)])
        except Exception as e: messagebox.showerror("Error", str(e))

    def _progress_animation_worker(self, widget_key, stop_event):
        val = 0.1
        while not stop_event.is_set():
            val = min(val + 0.005, 0.9)
            self._thread_safe_progress(widget_key, val); time.sleep(0.1)

    def _backport_worker(self, widget_key):
        with self.backport_semaphore:
            info = self.game_widgets[widget_key]
            source_path = info['source_path']; internal_path = info.get('internal_path', "")
            data = info['data']
            
            print(f"\n[BACKPORT] ========================================", flush=True)
            print(f"[BACKPORT] Starting: {data['titleName']} ({data['titleId']})", flush=True)
            
            safe_title = self._sanitize_filename(data['titleName'])
            out_name = f"{safe_title} - {data['titleId']} - {data['contentVersion']}"
            
            base_output_dir = self.backport_dir / out_name
            temp_extract_dir = None; overall_success = True; folders_processed = []
            is_archive = Path(source_path).is_file() and Path(source_path).suffix.lower().lstrip('.') in ['zip', 'rar', '7z']
            
            if is_archive:
                real_type = self.detect_real_archive_type(source_path)
                print(f"[BACKPORT] Source: {real_type.upper()} Archive -> {Path(source_path).name}", flush=True)
                if real_type == '7z' and not self.enable_7z_var.get():
                    print("[BACKPORT] ABORTED: 7z support is disabled in settings.", flush=True)
                    self.after(0, self._finish_backport, widget_key, False, [], "Skipped (7z disabled)", 0.0)
                    return
            else:
                print(f"[BACKPORT] Source: Normal Folder -> {source_path}", flush=True)

            start_time = time.time(); progress_stop_event = threading.Event()
            if not is_archive:
                self._thread_safe_btn_text(widget_key, "Backporting...")
                threading.Thread(target=self._progress_animation_worker, args=(widget_key, progress_stop_event), daemon=True).start()

            try:
                from Backport import PS5ELFProcessor
                
                processor = PS5ELFProcessor(use_colors=True)
                paid = 0x3100000000000002
                ptype = 1
                
                input_dir_to_process = source_path
                
                if is_archive:
                    self._thread_safe_btn_text(widget_key, "Extracting..."); self._thread_safe_progress(widget_key, 0.2)
                    real_type = self.detect_real_archive_type(source_path)
                    
                    print(f"[BACKPORT] Extracting entire archive to temp directory...", flush=True)
                    temp_extract_dir = tempfile.mkdtemp(prefix='ps5_backport_')
                    
                    try:
                        self._extract_required_files_only(source_path, real_type, temp_extract_dir, internal_path)
                        print(f"[BACKPORT] Extraction successful!", flush=True)
                    except Exception as e:
                        err_msg = str(e)
                        print(f"[BACKPORT] EXTRACTION FAILED: {err_msg}", flush=True)
                        shutil.rmtree(temp_extract_dir, ignore_errors=True)
                        temp_extract_dir = None
                        raise Exception(f"Failed to extract: {err_msg}")
                    
                    if internal_path:
                        input_dir_to_process = str(Path(temp_extract_dir) / internal_path)
                        if not os.path.exists(input_dir_to_process):
                            print(f"[BACKPORT] WARNING: Internal path '{internal_path}' not found, falling back to root.", flush=True)
                            input_dir_to_process = temp_extract_dir
                    else:
                        input_dir_to_process = temp_extract_dir
                        
                    print(f"[BACKPORT] Input directory for pipeline: {input_dir_to_process}", flush=True)
                    self._thread_safe_progress(widget_key, 0.4)

                selected_fakelib = info['fakelib_var'].get()
                do_all_fakelib = info['fakelib_all_var'].get()
                print(f"[BACKPORT] Fakelib: Selected='{selected_fakelib}', DoAll={do_all_fakelib}", flush=True)

                if do_all_fakelib:
                    fakelib_folders = [f.name for f in self.backport_dir.iterdir() if f.is_dir() and f.name.startswith("fakelib-")]
                    total = len(fakelib_folders)
                    print(f"[BACKPORT] Batch backporting with {total} fakelib versions...", flush=True)
                    for index, folder in enumerate(fakelib_folders):
                        sdk_pair = int(folder.replace("fakelib-", ""))
                        self._thread_safe_btn_text(widget_key, f"BP {index+1}/{total} (SDK {sdk_pair})")
                        specific_out = base_output_dir / folder; folders_processed.append(folder)
                        if not self._execute_single_backport(processor, input_dir_to_process, str(specific_out), sdk_pair, paid, ptype, str(self.backport_dir / folder)): overall_success = False
                        prog = (0.4 + (0.5 * (index + 1) / total)) if is_archive else (0.2 + (0.7 * (index + 1) / total))
                        self._thread_safe_progress(widget_key, prog)
                else:
                    sdk_pair = int(selected_fakelib) if selected_fakelib != "None" else 7
                    
                    out_dir = str(base_output_dir)
                    fakelib_path = None
                    if selected_fakelib != "None":
                        sdk_pair = int(selected_fakelib)
                        fakelib_folder_name = f"fakelib-{selected_fakelib}"
                        fakelib_path = str(self.backport_dir / fakelib_folder_name)
                        out_dir = str(base_output_dir / fakelib_folder_name)
                        folders_processed.append(fakelib_folder_name)
                    else:
                        sdk_pair = info.get('manual_sdk_override', 7)
                        fakelib_path = None
                        out_dir = str(base_output_dir)
                        folders_processed.append("No Fakelib")
                    
                    print(f"[BACKPORT] Executing single backport: SDK={sdk_pair}", flush=True)
                    self._thread_safe_btn_text(widget_key, f"Backporting (SDK {sdk_pair})")
                    self._thread_safe_progress(widget_key, 0.6)
                    
                    if not self._execute_single_backport(processor, input_dir_to_process, out_dir, sdk_pair, paid, ptype, fakelib_path): overall_success = False
                    
                self._thread_safe_btn_text(widget_key, "Finishing..."); self._thread_safe_progress(widget_key, 0.95)
                
            except Exception as e:
                error_msg = str(e)
                print(f"[BACKPORT ERROR] Pipeline failed: {error_msg}", flush=True)
                import traceback
                traceback.print_exc()
                overall_success = False
            finally:
                if not is_archive: progress_stop_event.set()
                if temp_extract_dir:
                    print(f"[BACKPORT] Cleaning up temp directory...", flush=True)
                    shutil.rmtree(temp_extract_dir, ignore_errors=True)
                elapsed_total = time.time() - start_time
                print(f"[BACKPORT] ========================================", flush=True)
                print(f"[BACKPORT] Completed in {elapsed_total:.2f}s. Success={overall_success}\n", flush=True)

                self.after(0, self._finish_backport, widget_key, overall_success, folders_processed, error_msg if not overall_success else "", elapsed_total)

    def _finish_backport(self, widget_key, success, processed, msg, elapsed_time):
        info = self.game_widgets.get(widget_key)
        if not info: return
        info['btn_start'].configure(text="Start", state="normal")
        info['is_processing'] = False
        time_str = f"{elapsed_time:.1f}s" if elapsed_time > 0 else ""
        
        if success:
            info['progress'].set(1.0)
            
            is_backported, bp_info = self.check_backport_status(info["data"]["titleName"], info["data"]["titleId"], info["data"]["contentVersion"])
            
            if is_backported:
                status_text = f"Backported ({', '.join(bp_info)})" if bp_info else "Backported"
                info['status_label'].configure(text=status_text, text_color="#00FF00")
            else:
                info['status_label'].configure(text="Backported", text_color="#00FF00")
                
            info['is_backported'] = True
        else:
            info['progress'].set(0)
            info['status_label'].configure(text=f"Failed: {msg}", text_color="#FF4444")
            
        if time_str:
            info['time_label'].configure(text=time_str, text_color="#00FF00" if success else "#FF4444")

    def _execute_single_backport(self, processor, input_dir, output_dir, sdk_pair, paid, ptype, fakelib_source):
        res = processor.decrypt_and_sign_pipeline(input_dir=input_dir, output_dir=output_dir, sdk_pair=sdk_pair, paid=paid, ptype=ptype, fakelib_source=fakelib_source, create_backup=True, overwrite=False, apply_libc_patch=True, auto_revert_for_high_sdk=True, verbose=True)
        return not (res.get('failed', 0) > 0 or res.get('decrypt', {}).get('failed', 0) > 0)

    def check_backport_status(self, title_name, title_id, game_version):
        safe_title = self._sanitize_filename(title_name)
        folder_path = self.backport_dir / f"{safe_title} - {title_id} - {game_version}"
        if not folder_path.is_dir(): return False, []
        fakelib_found = []
        try:
            for item in folder_path.iterdir():
                if item.is_dir() and item.name.startswith("fakelib-") and any(item.iterdir()): fakelib_found.append(item.name)
            if any(item.is_file() and not item.name.startswith(".") for item in folder_path.iterdir()): fakelib_found.insert(0, "direct")
        except OSError: pass
        return len(fakelib_found) > 0, fakelib_found

    def detect_real_archive_type(self, filepath):
        try:
            with open(filepath, 'rb') as f: header = f.read(6)
            if header[:2] == b'PK': return 'zip'
            elif header[:4] == b'Rar!': return 'rar'
            elif header[:6] == b'7z\xbc\xaf\x27\x1c': return '7z'
        except: pass
        return None

    # --- Archive Helpers ---
    def _extract_archive_files(self, archive_path, real_type, dest_dir, valid_exts):
        try:
            if real_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as z:
                    for f in z.namelist():
                        if Path(f).suffix.lower() in valid_exts: z.extract(f, dest_dir)
            elif real_type == 'rar':
                with rarfile.RarFile(archive_path, 'r') as z:
                    for f in z.namelist():
                        if Path(f).suffix.lower() in valid_exts: z.extract(f, dest_dir)
            elif real_type == '7z':
                with py7zr.SevenZipFile(archive_path, 'r') as z:
                    targets = [n for n in z.getnames() if Path(n).suffix.lower() in valid_exts]
                    if targets: z.extract(targets=targets, path=dest_dir)
        except Exception as e: print(f"[EXTRACT ERROR] {e}")

    def _extract_all_archive_files(self, archive_path, real_type, dest_dir):
        """Extracts ALL files from an archive to a destination directory."""
        try:
            if real_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as z:
                    z.extractall(dest_dir)
            elif real_type == 'rar':
                with rarfile.RarFile(archive_path, 'r') as z:
                    z.extractall(dest_dir)
            elif real_type == '7z':
                with py7zr.SevenZipFile(archive_path, 'r') as z:
                    z.extractall(path=dest_dir)
        except Exception as e:
            raise Exception(f"Failed to extract archive: {e}")
    
    def _extract_required_files_only(self, archive_path, real_type, dest_dir, internal_path=""):
        """Extract ONLY the files required for backporting (param.json + executables)."""
        try:
            targets_to_extract = []
            exec_exts = ['.self', '.prx', '.sprx', '.elf']
            
            # 1. Figure out which files we need
            if real_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for name in zf.namelist():
                        norm = name.replace('\\', '/').lower()
                        if internal_path and not norm.startswith(internal_path.lower() + '/'):
                            continue
                        if norm.endswith('sce_sys/param.json') or norm.endswith('eboot.bin'):
                            targets_to_extract.append(name)
                        elif any(norm.endswith(ext) for ext in exec_exts):
                            targets_to_extract.append(name)
                            
            elif real_type == 'rar':
                with rarfile.RarFile(archive_path, 'r') as rf:
                    for name in rf.namelist():
                        norm = name.replace('\\', '/').lower()
                        if internal_path and not norm.startswith(internal_path.lower() + '/'):
                            continue
                        if norm.endswith('sce_sys/param.json') or norm.endswith('eboot.bin'):
                            targets_to_extract.append(name)
                        elif any(norm.endswith(ext) for ext in exec_exts):
                            targets_to_extract.append(name)
                            
            elif real_type == '7z':
                with py7zr.SevenZipFile(archive_path, 'r') as szf:
                    for name in szf.getnames():
                        norm = name.replace('\\', '/').lower()
                        if internal_path and not norm.startswith(internal_path.lower() + '/'):
                            continue
                        if norm.endswith('sce_sys/param.json') or norm.endswith('eboot.bin'):
                            targets_to_extract.append(name)
                        elif any(norm.endswith(ext) for ext in exec_exts):
                            targets_to_extract.append(name)

            if not targets_to_extract:
                raise Exception(f"No backportable executable files found inside archive.")
                
            print(f"[BACKPORT] Smart extract: Found {len(targets_to_extract)} required file(s) to extract.", flush=True)
            for t in targets_to_extract[:5]:
                print(f"[BACKPORT]   - {t}", flush=True)
            if len(targets_to_extract) > 5:
                print(f"[BACKPORT]   - ... and {len(targets_to_extract) - 5} more", flush=True)

            # 2. Extract ONLY those files
            if real_type == 'zip':
                with zipfile.ZipFile(archive_path, 'r') as zf:
                    for name in targets_to_extract:
                        zf.extract(name, dest_dir)
                        
            elif real_type == 'rar':
                with rarfile.RarFile(archive_path, 'r') as rf:
                    rf.extractall(dest_dir, members=targets_to_extract)
                    
            elif real_type == '7z':
                try:
                    # Try targeted extraction first (fast for non-solid archives)
                    with py7zr.SevenZipFile(archive_path, 'r') as szf:
                        szf.extract(targets=targets_to_extract, path=dest_dir)
                except Exception as e:
                    print(f"[BACKPORT] 7z targeted extract failed ({e}).", flush=True)
                    print(f"[BACKPORT] Falling back to safe extraction...", flush=True)
                    
                    # Fallback: Use py7zr to extract all, but we will delete unnecessary files after
                    with py7zr.SevenZipFile(archive_path, 'r') as szf:
                        szf.extractall(path=dest_dir)
                    
                    # If it was a multi-game archive, delete the other games to save space
                    if internal_path:
                        temp_root = Path(dest_dir)
                        for item in temp_root.iterdir():
                            if item.name.lower() != internal_path.lower().split('/')[0]:
                                if item.is_dir():
                                    shutil.rmtree(item, ignore_errors=True)
                                else:
                                    item.unlink()
                                    
        except Exception as e:
            raise Exception(f"Smart extraction failed: {e}")
        
    # =====================================================================
    # PS5 GAME SCANNING IMPLEMENTATION
    # =====================================================================
    
    def _find_file_in_namelist(self, namelist, target_suffix):
        """Find a file in archive namelist by suffix (case-insensitive)."""
        target_lower = target_suffix.lower()
        for name in namelist:
            norm_name = name.replace('\\', '/')
            if norm_name.lower().endswith(target_lower):
                return name
        return None

    def _find_all_files_in_namelist(self, namelist, target_suffix):
        """Find ALL files in archive namelist by suffix (case-insensitive)."""
        target_lower = target_suffix.lower()
        matches = []
        for name in namelist:
            norm_name = name.replace('\\', '/')
            if norm_name.lower().endswith(target_lower):
                matches.append(name)
        return matches

    def _format_version(self, version_str):
        """Convert version string to human-readable format."""
        if not version_str or version_str == 'N/A':
            return 'N/A'
        
        version_str = str(version_str).strip()
        
        if version_str.lower().startswith('0x'):
            hex_part = version_str[2:]
            if len(hex_part) >= 2:
                result = hex_part[:2]
                if len(result) == 2 and result[0] == '0' and result[1].isdigit():
                    result = result[1]
                return result
            return version_str
        
        if '.' in version_str:
            parts = version_str.split('.')
            return parts[0]
        
        return version_str

    def _extract_game_data_from_param(self, param_data):
        """Extract required fields from param.json data."""
        
        title_name = None
        
        if not title_name:
            title_name = param_data.get('titleName')
            
        if not title_name:
            title_obj = param_data.get('title', {})
            if isinstance(title_obj, dict):
                title_name = title_obj.get('en') or title_obj.get('EN') or title_obj.get('english')
                if not title_name:
                    for key, value in title_obj.items():
                        if isinstance(value, str) and len(value.strip()) > 0:
                            title_name = value
                            break
                            
        if not title_name:
            loc_params = param_data.get('localizedParameters', {})
            if isinstance(loc_params, dict):
                default_lang = loc_params.get('defaultLanguage')
                if default_lang and isinstance(loc_params.get(default_lang), dict):
                    title_name = loc_params.get(default_lang, {}).get('titleName')
                
                if not title_name:
                    for lang_key in ['en-US', 'en-GB', 'en-AU', 'en']:
                        if isinstance(loc_params.get(lang_key), dict):
                            title_name = loc_params.get(lang_key, {}).get('titleName')
                            if title_name:
                                break
                                
                if not title_name:
                    for lang_key, lang_data in loc_params.items():
                        if isinstance(lang_data, dict) and lang_key != 'defaultLanguage':
                            title_name = lang_data.get('titleName')
                            if title_name:
                                break
                                
        if not title_name:
            title_name = "Unknown Title"
            
        raw_title_id = param_data.get('titleId', 'N/A')
        title_id = str(raw_title_id).upper() if raw_title_id else 'N/A'
            
        return {
            'titleId': title_id,
            'contentVersion': param_data.get('contentVersion', 'N/A'),
            'sdkVersion': self._format_version(param_data.get('sdkVersion', 'N/A')),
            'requiredSystemSoftwareVersion': self._format_version(param_data.get('requiredSystemSoftwareVersion', 'N/A')),
            'contentId': param_data.get('contentId', 'N/A'),
            'titleName': title_name
        }

    def _process_icon_bytes(self, icon_bytes):
        """Process icon bytes to base64 and PIL image."""
        if not icon_bytes:
            return None, None
        try:
            img_b64 = base64.b64encode(icon_bytes).decode('utf-8')
            pil_image = Image.open(io.BytesIO(icon_bytes)).resize((128, 128), Image.Resampling.LANCZOS)
            return img_b64, pil_image
        except Exception as e:
            print(f"[ICON ERROR] Failed to process icon: {e}")
            return None, None

    def _scan_folder(self, folder_path):
        """Scan a folder for PS5 game param.json and icon0.png."""
        folder = Path(folder_path)
        sce_sys = folder / 'sce_sys'
        param_file = sce_sys / 'param.json'
        icon_file = sce_sys / 'icon0.png'
        
        if not param_file.exists():
            return None
        
        try:
            with open(param_file, 'r', encoding='utf-8-sig') as f:
                param_data = json.load(f)
            
            game_data = self._extract_game_data_from_param(param_data)
            
            if game_data['titleId'] == 'N/A':
                print(f"[SCAN] Skipped (Invalid Title ID): {folder_path}", flush=True)
                return None
            
            print(f"[SCAN] Found Folder Game: {game_data['titleName']} ({game_data['titleId']})", flush=True)
            
            img_b64 = None
            pil_image = None
            if icon_file.exists():
                try:
                    with open(icon_file, 'rb') as img_f:
                        img_b64, pil_image = self._process_icon_bytes(img_f.read())
                except Exception as e:
                    print(f"[SCAN ICON ERROR] Failed to read {icon_file}: {e}", flush=True)
            
            return {
                'data': game_data,
                'pil_image': pil_image,
                'img_b64': img_b64,
                'source_type': 'Normal Folder',
                'source_path': str(folder),
                'internal_path': ''
            }
            
        except json.JSONDecodeError as e:
            print(f"[SCAN ERROR] Invalid JSON in {param_file}: {e}", flush=True)
            return None
        except Exception as e:
            print(f"[SCAN ERROR] Failed to scan folder {folder_path}: {e}", flush=True)
            return None

    def _scan_archive(self, archive_path):
        """Scan an archive for PS5 games. Returns LIST of all games found."""
        path = Path(archive_path)
        real_type = self.detect_real_archive_type(str(path))
        
        if not real_type:
            print(f"[SCAN] Skipped (Unknown format): {path.name}", flush=True)
            return []
        
        if real_type == '7z' and not self.enable_7z_var.get():
            print(f"[SCAN] Skipped (7z disabled): {path.name}", flush=True)
            return []
        
        print(f"[SCAN] Scanning {real_type.upper()} Archive: {path.name}", flush=True)
        
        try:
            results = []
            source_type = f"{real_type.upper()} Archive"
            
            if real_type == 'zip':
                with zipfile.ZipFile(str(path), 'r') as zf:
                    namelist = zf.namelist()
                    print(f"[SCAN] -> ZIP contains {len(namelist)} item(s).", flush=True)
                    param_names = self._find_all_files_in_namelist(namelist, 'sce_sys/param.json')
                    print(f"[SCAN] -> Found {len(param_names)} param.json file(s).", flush=True)
                    
                    for param_name in param_names:
                        try:
                            with zf.open(param_name) as f:
                                content = f.read().decode('utf-8-sig')
                                param_data = json.loads(content)
                            
                            norm_name = param_name.replace('\\', '/')
                            parts = norm_name.split('/')
                            internal_path = '/'.join(parts[:-2]) if len(parts) > 2 else ''
                            
                            icon_prefix = norm_name.rsplit('param.json', 1)[0]
                            icon_name = next((n for n in namelist if n.replace('\\', '/').lower() == (icon_prefix + 'icon0.png').lower()), None)
                            
                            icon_bytes = None
                            if icon_name:
                                with zf.open(icon_name) as f:
                                    icon_bytes = f.read()
                            
                            if param_data:
                                game_data = self._extract_game_data_from_param(param_data)
                                if game_data['titleId'] != 'N/A':
                                    img_b64, pil_image = self._process_icon_bytes(icon_bytes)
                                    results.append({
                                        'data': game_data, 'pil_image': pil_image, 'img_b64': img_b64,
                                        'source_type': source_type, 'source_path': str(path),
                                        'internal_path': internal_path
                                    })
                                    print(f"[SCAN] -> Found Game: {game_data['titleName']} ({game_data['titleId']})", flush=True)
                        except Exception as e:
                            print(f"[SCAN ERROR] Failed to process {param_name} in {path.name}: {e}", flush=True)
                            continue
        
            elif real_type == 'rar':
                try:
                    with rarfile.RarFile(str(path), 'r') as rf:
                        namelist = rf.namelist()
                        print(f"[SCAN] -> RAR contains {len(namelist)} item(s).", flush=True)
                        
                        # ============ DEBUG: Show first 10 file paths ============
                        print(f"[DEBUG] Tool: {rarfile.UNRAR_TOOL}", flush=True)
                        for n in namelist[:10]:
                            print(f"[DEBUG PATH] {repr(n)}", flush=True)
                        # =========================================================
                        
                        param_names = self._find_all_files_in_namelist(namelist, 'sce_sys/param.json')
                        print(f"[SCAN] -> Found {len(param_names)} param.json file(s).", flush=True)
                        
                        for param_name in param_names:
                            try:
                                print(f"[DEBUG] Opening: {repr(param_name)}", flush=True)
                                with rf.open(param_name) as f:
                                    content = f.read()
                                    param_data = None
                                    for encoding in ['utf-8-sig', 'utf-8', 'latin-1']:
                                        try:
                                            param_data = json.loads(content.decode(encoding))
                                            break
                                        except (UnicodeDecodeError, json.JSONDecodeError):
                                            continue
                                
                                norm_name = param_name.replace('\\', '/')
                                parts = norm_name.split('/')
                                internal_path = '/'.join(parts[:-2]) if len(parts) > 2 else ''
                                
                                icon_prefix = norm_name.rsplit('param.json', 1)[0]
                                icon_name = next((n for n in namelist if n.replace('\\', '/').lower() == (icon_prefix + 'icon0.png').lower()), None)
                                
                                icon_bytes = None
                                if icon_name:
                                    try:
                                        with rf.open(icon_name) as f:
                                            icon_bytes = f.read()
                                    except Exception as icon_err:
                                        print(f"[DEBUG] Icon failed: {icon_err}", flush=True)
                                
                                if param_data:
                                    game_data = self._extract_game_data_from_param(param_data)
                                    if game_data['titleId'] != 'N/A':
                                        img_b64, pil_image = self._process_icon_bytes(icon_bytes)
                                        results.append({
                                            'data': game_data, 'pil_image': pil_image, 'img_b64': img_b64,
                                            'source_type': source_type, 'source_path': str(path),
                                            'internal_path': internal_path
                                        })
                                        print(f"[SCAN] -> Found Game: {game_data['titleName']} ({game_data['titleId']})", flush=True)
                            except Exception as e:
                                print(f"[SCAN ERROR] Failed to process {param_name} in {path.name}: {e}", flush=True)
                                import traceback
                                traceback.print_exc()
                                continue
                except Exception as e:
                    print(f"[SCAN ERROR] Failed to open RAR {path.name}: {e}", flush=True)
                    import traceback
                    traceback.print_exc()
                    return []
        
            elif real_type == '7z':
                with py7zr.SevenZipFile(str(path), 'r') as szf:
                    namelist = szf.getnames()
                    print(f"[SCAN] -> 7z contains {len(namelist)} item(s).", flush=True)
                    param_names = self._find_all_files_in_namelist(namelist, 'sce_sys/param.json')
                    print(f"[SCAN] -> Found {len(param_names)} param.json file(s).", flush=True)
                    icon_names = self._find_all_files_in_namelist(namelist, 'sce_sys/icon0.png')
                    
                    for param_name in param_names:
                        try:
                            norm_name = param_name.replace('\\', '/')
                            parts = norm_name.split('/')
                            internal_path = '/'.join(parts[:-2]) if len(parts) > 2 else ''
                            
                            icon_prefix = norm_name.rsplit('param.json', 1)[0]
                            icon_name = next((n for n in icon_names if n.replace('\\', '/').lower() == (icon_prefix + 'icon0.png').lower()), None)
                            
                            targets = [param_name]
                            if icon_name: targets.append(icon_name)
                            
                            with tempfile.TemporaryDirectory() as tmp:
                                szf.extract(targets=targets, path=tmp)
                                
                                param_file = Path(tmp) / param_name
                                param_data = None
                                if param_file.exists():
                                    with open(param_file, 'r', encoding='utf-8-sig') as f:
                                        param_data = json.load(f)
                                
                                icon_bytes = None
                                if icon_name:
                                    icon_file = Path(tmp) / icon_name
                                    if icon_file.exists():
                                        with open(icon_file, 'rb') as f:
                                            icon_bytes = f.read()
                            
                            if param_data:
                                game_data = self._extract_game_data_from_param(param_data)
                                if game_data['titleId'] != 'N/A':
                                    img_b64, pil_image = self._process_icon_bytes(icon_bytes)
                                    results.append({
                                        'data': game_data, 'pil_image': pil_image, 'img_b64': img_b64,
                                        'source_type': source_type, 'source_path': str(path),
                                        'internal_path': internal_path
                                    })
                                    print(f"[SCAN] -> Found Game: {game_data['titleName']} ({game_data['titleId']})", flush=True)
                        except Exception as e:
                            print(f"[SCAN ERROR] Failed to process {param_name} in {path.name}: {e}", flush=True)
                            continue
        
            return results
            
        except Exception as e:
            print(f"[SCAN ERROR] Failed to scan archive {path.name}: {e}", flush=True)
            return []

    def _scan_single_item(self, task_type, task_path, ignore_cache):
        """Scan a single folder or archive for PS5 game data. Returns LIST of results."""
        results = []
        
        if task_type == 'folder':
            cache_key = f"{task_path}||"
            
            if not ignore_cache and cache_key in self.games_cache:
                cached = self.games_cache[cache_key]
                if cached.get('data', {}).get('titleId') != 'N/A':
                    pil_image = None
                    if cached.get('img_b64'):
                        try:
                            pil_image = Image.open(io.BytesIO(base64.b64decode(cached['img_b64']))).resize((128, 128), Image.Resampling.LANCZOS)
                        except:
                            pass
                    results.append({
                        'data': cached['data'],
                        'pil_image': pil_image,
                        'img_b64': cached.get('img_b64'),
                        'source_type': cached.get('source_type', 'Normal Folder'),
                        'source_path': task_path,
                        'internal_path': ''
                    })
                    return results
            
            result = self._scan_folder(task_path)
            if result:
                results.append(result)
            return results
        
        elif task_type == 'archive':
            # For archives, check cache first for all games from this archive
            if not ignore_cache:
                cached_results = []
                for cache_key, cached in self.games_cache.items():
                    # Check if this cache entry belongs to this archive
                    if cache_key.startswith(f"{task_path}||") and cache_key != f"{task_path}||":
                        if cached.get('data', {}).get('titleId') != 'N/A':
                            pil_image = None
                            if cached.get('img_b64'):
                                try:
                                    pil_image = Image.open(io.BytesIO(base64.b64decode(cached['img_b64']))).resize((128, 128), Image.Resampling.LANCZOS)
                                except:
                                    pass
                            _, internal_path = cache_key.split("||", 1)
                            cached_results.append({
                                'data': cached['data'],
                                'pil_image': pil_image,
                                'img_b64': cached.get('img_b64'),
                                'source_type': cached.get('source_type', ''),
                                'source_path': task_path,
                                'internal_path': internal_path
                            })
                
                if cached_results:
                    return cached_results
            
            # Not in cache or ignoring cache - scan the archive
            return self._scan_archive(task_path)
        
        return []
    
    def _deduplicate_games(self, results):
        """Remove duplicates, prioritizing archives over folders (except 7z)."""
        def get_priority(source_type):
            st = source_type.upper()
            if 'ZIP' in st: return 1
            elif 'RAR' in st: return 2
            elif '7Z' in st: return 4
            else: return 3
        
        games_by_title = {}
        for result in results:
            title_id = result['data']['titleId']
            if title_id not in games_by_title:
                games_by_title[title_id] = []
            games_by_title[title_id].append(result)
        
        final_results = []
        for title_id, games in games_by_title.items():
            sorted_games = sorted(games, key=lambda g: get_priority(g['source_type']))
            final_results.append(sorted_games[0])
        
        return final_results

    def _scan_worker(self, root_path, ignore_cache=False):
        """Worker thread that scans for PS5 games in folders and archives."""
        print(f"\n[SCAN] ========================================", flush=True)
        print(f"[SCAN] Starting scan: {root_path}", flush=True)
        print(f"[SCAN] Ignore cache: {ignore_cache}", flush=True)
        try:
            self._show_scan_progress()
            self._thread_safe_status("Scanning...", "yellow")
            
            max_threads = int(self.max_scan_threads_var.get())
            valid_archive_exts = {'.zip', '.rar', '.7z'}
            
            root = Path(root_path)
            scan_tasks = []
            
            # 1. Find folders
            print(f"[SCAN] Searching for game folders...", flush=True)
            for sce_sys_dir in root.rglob('sce_sys'):
                if any(part.startswith('.') or part.startswith('@') for part in sce_sys_dir.parts):
                    continue
                if sce_sys_dir.is_dir():
                    param_file = sce_sys_dir / 'param.json'
                    if param_file.exists():
                        game_folder = sce_sys_dir.parent
                        scan_tasks.append(('folder', str(game_folder)))
            print(f"[SCAN] Found {len([t for t in scan_tasks if t[0] == 'folder'])} folder(s).", flush=True)
            
            # 2. Find archives
            print(f"[SCAN] Searching for archives...", flush=True)
            for archive_path in root.rglob('*'):
                if any(part.startswith('.') or part.startswith('@') for part in archive_path.parts):
                    continue
                if archive_path.is_file() and archive_path.suffix.lower() in valid_archive_exts:
                    scan_tasks.append(('archive', str(archive_path)))
            print(f"[SCAN] Found {len([t for t in scan_tasks if t[0] == 'archive'])} archive(s).", flush=True)
            
            total_tasks = len(scan_tasks)
            
            if total_tasks == 0:
                print(f"[SCAN] No items found to scan.", flush=True)
                self._thread_safe_status("No games found.", "gray")
                return
            
            self._thread_safe_status(f"Scanning {total_tasks} items...", "yellow")
            
            # Process tasks
            all_results = []
            completed = 0
            
            with ThreadPoolExecutor(max_workers=max_threads) as executor:
                future_to_task = {
                    executor.submit(self._scan_single_item, task_type, task_path, ignore_cache): (task_type, task_path) 
                    for task_type, task_path in scan_tasks
                }
                
                for future in as_completed(future_to_task):
                    try:
                        results = future.result()
                        if results:
                            all_results.extend(results)
                    except Exception as e:
                        task_type, task_path = future_to_task[future]
                        print(f"[SCAN ERROR] {task_type} {task_path}: {e}", flush=True)
                    
                    completed += 1
                    self._update_scan_progress(completed / total_tasks)
            
            # Deduplicate
            deduplicated_results = self._deduplicate_games(all_results)
            
            # Add to GUI
            added_count = 0
            for result in deduplicated_results:
                status = self._process_result(
                    result['data'], result['pil_image'], result['source_type'],
                    result['source_path'], result.get('internal_path', '')
                )
                if status == 'success':
                    added_count += 1
                    cache_key = f"{result['source_path']}||{result.get('internal_path', '')}"
                    self.games_cache[cache_key] = {
                        'data': result['data'],
                        'img_b64': result.get('img_b64'),
                        'source_type': result['source_type']
                    }
            
            self._save_games_cache()
            duplicate_count = len(all_results) - len(deduplicated_results)
            
            print(f"[SCAN] Total raw results: {len(all_results)}", flush=True)
            print(f"[SCAN] Duplicates hidden: {duplicate_count}", flush=True)
            print(f"[SCAN] Games added to GUI: {added_count}", flush=True)
            print(f"[SCAN] ========================================\n", flush=True)
            
            if added_count > 0:
                msg = f"Found {added_count} game(s)."
                if duplicate_count > 0:
                    msg += f" ({duplicate_count} duplicate(s) hidden)"
                self._thread_safe_status(msg, "green")
            else:
                self._thread_safe_status("No valid games found.", "orange")
            
        except Exception as e:
            print(f"[SCAN ERROR] {e}", flush=True)
            import traceback
            traceback.print_exc()
            self._thread_safe_status(f"Scan error: {str(e)}", "red")
        
        finally:
            def finish(): 
                self.browse_btn.configure(state="normal")
                self.refresh_btn.configure(state="normal")
                self.is_scanning = False
                self.after(500, self._hide_scan_progress)
            self.after(0, finish)

    # --- Scanning & GUI Populating ---
    def load_from_cache_on_startup(self):
        if not self.games_cache: 
            self.status_label.configure(text="No cache found.", text_color="gray")
            return
        
        self.clear_list()
        self.status_label.configure(text="Loading cache...", text_color="yellow")
        self.update_idletasks()
        
        allow_7z = self.app_settings.get("enable_7z", False)
        total = len(self.games_cache)
        self._show_scan_progress()
        
        # Collect all cached results first
        all_cached = []
        for i, (key, entry) in enumerate(self.games_cache.items()):
            sp, ip = key.split("||", 1) if "||" in key else (key, "")
            gd = entry.get("data")
            if not gd or gd.get("titleId") == "N/A":
                continue
            if not allow_7z and ".7Z" in entry.get("source_type", ""):
                continue
            
            pil = None
            if entry.get("img_b64"):
                try:
                    pil = Image.open(io.BytesIO(base64.b64decode(entry["img_b64"]))).resize((128, 128), Image.Resampling.LANCZOS)
                except:
                    pass
            
            all_cached.append({
                'data': gd,
                'pil_image': pil,
                'img_b64': entry.get('img_b64'),
                'source_type': entry.get("source_type", "Normal Folder"),
                'source_path': sp,
                'internal_path': ip
            })
            
            self._update_scan_progress((i + 1) / total if total > 0 else 1)
        
        # DEDUPLICATE cached results
        deduplicated = self._deduplicate_games(all_cached)
        
        # Add deduplicated results to GUI
        loaded = 0
        for result in deduplicated:
            self._process_result(
                result['data'],
                result['pil_image'],
                result['source_type'],
                result['source_path'],
                result.get('internal_path', '')
            )
            loaded += 1
        
        # Count hidden duplicates
        duplicate_count = len(all_cached) - len(deduplicated)
        
        msg = f"Loaded {loaded} games from cache."
        if duplicate_count > 0:
            msg += f" ({duplicate_count} duplicate(s) hidden)"
        
        self.status_label.configure(text=msg, text_color="green")
        self.after(500, self._hide_scan_progress)

    def _periodic_sync_loop(self):
        """Background loop that checks for new games every 5 seconds."""
        while True:
            time.sleep(5)
            try:
                # FIX: Thread safety check using boolean flag instead of cget
                if self.is_scanning:
                    continue

                last_folder = self.app_settings.get("latest_folder")
                if not last_folder or not os.path.exists(last_folder):
                    continue
                
                if self._check_for_new_items(last_folder):
                    self._run_incremental_sync(last_folder)
            except Exception:
                # Ignore transient errors
                pass

    def _check_for_new_items(self, root_path):
        """Quickly check if there are any new folders or archives without doing a heavy scan."""
        root = Path(root_path)
        valid_archive_exts = {'.zip', '.rar', '.7z'}
        
        # 1. Check folders
        for sce_sys_dir in root.rglob('sce_sys'):
            if any(part.startswith('.') or part.startswith('@') for part in sce_sys_dir.parts):
                continue
            if sce_sys_dir.is_dir():
                param_file = sce_sys_dir / 'param.json'
                if param_file.exists():
                    game_folder = sce_sys_dir.parent
                    cache_key = f"{game_folder}||"
                    if cache_key not in self.games_cache:
                        return True # Found a new folder
                        
        # 2. Check archives
        for archive_path in root.rglob('*'):
            if any(part.startswith('.') or part.startswith('@') for part in archive_path.parts):
                continue
            if archive_path.is_file() and archive_path.suffix.lower() in valid_archive_exts:
                archive_prefix = f"{archive_path}||"
                has_cached_games = any(k.startswith(archive_prefix) and k != archive_prefix for k in self.games_cache.keys())
                
                if not has_cached_games:
                    real_type = self.detect_real_archive_type(str(archive_path))
                    if real_type == '7z' and not self.enable_7z_var.get():
                        continue
                    return True # Found a new archive
                    
        return False

    def _run_incremental_sync(self, root_path):
        """Scan and add only the newly detected games to the GUI."""
        print(f"\n[AUTO-SYNC] New files detected, running incremental scan...", flush=True)
        root = Path(root_path)
        new_results = []
        valid_archive_exts = {'.zip', '.rar', '.7z'}
        
        try:
            for sce_sys_dir in root.rglob('sce_sys'):
                if any(part.startswith('.') or part.startswith('@') for part in sce_sys_dir.parts):
                    continue
                if sce_sys_dir.is_dir():
                    param_file = sce_sys_dir / 'param.json'
                    if param_file.exists():
                        game_folder = sce_sys_dir.parent
                        cache_key = f"{game_folder}||"
                        if cache_key not in self.games_cache:
                            result = self._scan_folder(str(game_folder))
                            if result:
                                new_results.append(result)

            for archive_path in root.rglob('*'):
                if any(part.startswith('.') or part.startswith('@') for part in archive_path.parts):
                    continue
                if archive_path.is_file() and archive_path.suffix.lower() in valid_archive_exts:
                    archive_prefix = f"{archive_path}||"
                    has_cached_games = any(k.startswith(archive_prefix) and k != archive_prefix for k in self.games_cache.keys())
                    
                    if not has_cached_games:
                        real_type = self.detect_real_archive_type(str(archive_path))
                        if real_type == '7z' and not self.enable_7z_var.get():
                            continue
                        results = self._scan_archive(str(archive_path))
                        new_results.extend(results)
                        
                        # FIX: Save an empty/failed marker to cache so we don't spam scan it every 5 seconds
                        if not results:
                            self.games_cache[f"{archive_path}||__SCAN_FAILED__"] = {
                                'data': {'titleId': 'N/A'}, 
                                'source_type': 'Failed Scan'
                            }

            if not new_results:
                print(f"[AUTO-SYNC] No new valid games found.", flush=True)
                return

            deduplicated = self._deduplicate_games(new_results)
            
            added_count = 0
            for result in deduplicated:
                status = self._process_result(
                    result['data'], result['pil_image'], result['source_type'],
                    result['source_path'], result.get('internal_path', '')
                )
                if status == 'success':
                    added_count += 1
                    cache_key = f"{result['source_path']}||{result.get('internal_path', '')}"
                    self.games_cache[cache_key] = {
                        'data': result['data'],
                        'img_b64': result.get('img_b64'),
                        'source_type': result['source_type']
                    }

            if added_count > 0:
                self._save_games_cache()
                print(f"[AUTO-SYNC] Auto-added {added_count} game(s).", flush=True)
                self._thread_safe_status(f"Auto-added {added_count} new game(s).", "green")
            else:
                print(f"[AUTO-SYNC] Games found, but skipped as duplicates.", flush=True)
                self._thread_safe_status("Up to date.", "green")

        except Exception as e:
            print(f"[AUTO-SYNC ERROR] {e}", flush=True)

    def save_settings(self, folder_path):
        self._on_settings_changed(); self.app_settings["latest_folder"] = folder_path
        try:
            with open(self.settings_file, 'w', encoding='utf-8') as f: json.dump(self.app_settings, f, indent=4)
        except: pass

    def browse_folder(self):
        p = filedialog.askdirectory(title="Select Root Folder", initialdir=self.app_settings.get("latest_folder", str(Path.home())))
        if p: self.save_settings(p); self.scan_folders_recursively(p)

    def force_refresh_cache(self):
        lf = self.app_settings.get("latest_folder")
        if not lf or lf in [str(Path.home()), "C:\\", "/"]: messagebox.showinfo("Info", "No folder selected."); return
        if messagebox.askyesno("Refresh", "Rescan everything?"):
            self.clear_list(); self.scan_folders_recursively(lf, ignore_cache=True)

    def scan_folders_recursively(self, root_path, ignore_cache=False):
        self.clear_list(); self.browse_btn.configure(state="disabled"); self.refresh_btn.configure(state="disabled")
        self.is_scanning = True
        self._thread_safe_status("Starting scan...", "yellow")
        threading.Thread(target=self._scan_worker, args=(root_path, ignore_cache), daemon=True).start()

    def _process_result(self, game_data, pil_image, source_type, source_path, internal_path=""):
        if not game_data or game_data.get("titleId") == "N/A": return "na"
        
        # Use composite key for deduplication: source_path||internal_path
        dedupe_key = f"{source_path}||{internal_path}"
        
        with self.seen_game_keys_lock:
            if dedupe_key in self.seen_game_keys: return "dup"
            self.seen_game_keys.add(dedupe_key)
        
        self._thread_safe_add(game_data, pil_image, source_type, source_path, internal_path)
        return "success"

    def clear_list(self):
        self.instr_label.pack(pady=(10, 5)); self.browse_btn.pack_forget(); self.refresh_btn.pack_forget(); self.scan_progress_frame.pack_forget()
        for w in self.scrollable_frame.winfo_children(): w.destroy()
        self.seen_game_keys.clear(); self.game_widgets.clear()
        if self.view_mode_var.get() == "Grid": self.scrollable_frame.grid_columnconfigure((0, 1, 2), weight=1)

    def add_to_gui(self, game_data, pil_image, source_type, source_path, internal_path=""):
        widget_key = f"{source_path}||{internal_path}"
        
        mode = "grid" if self.view_mode_var.get() == "Grid" else "list"
        cols = 3 if mode == "grid" else 1
        index = len(self.game_widgets)
        row, col = index // cols, index % cols
        
        self.game_widgets[widget_key] = {
            "progress": None, "status_label": None, "btn_start": None, 
            "fakelib_var": None, "fakelib_all_var": None, "fakelib_menu": None, 
            "time_label": None, "progress_frame": None, "data": game_data, 
            "is_backported": False, "pil_image": pil_image, "source_path": source_path, 
            "source_type": source_type, "internal_path": internal_path, "is_processing": False
        }
        
        p, s, b, fv, fav, fm, t, pf = self.create_list_item(
            game_data, pil_image, source_type, widget_key, 
            mode=mode, row=row, col=col, internal_path=internal_path
        )
        
        title_id = game_data["titleId"]
        is_backported, _ = self.check_backport_status(
            game_data["titleName"], title_id, game_data["contentVersion"]
        )
        self.game_widgets[widget_key].update({
            "progress": p, "status_label": s, "btn_start": b, "fakelib_var": fv, 
            "fakelib_all_var": fav, "fakelib_menu": fm, "time_label": t, 
            "progress_frame": pf, "is_backported": is_backported
        })
        
        if len(self.game_widgets) == 1:
            self.instr_label.pack_forget()
            self.browse_btn.pack(side="left", padx=5)
            self.refresh_btn.pack(side="left", padx=5)

    def create_list_item(self, data, pil_image, source_type, widget_key, mode="list", row=0, col=0, internal_path=""):
        if internal_path:
            if len(internal_path) > 40:
                display_path = "..." + internal_path[-37:]
            else:
                display_path = internal_path
            internal_path_label = f" {display_path}"
        else:
            internal_path_label = ""
        
        if mode == "grid":
            cell = ctk.CTkFrame(self.scrollable_frame); cell.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
            pf = ctk.CTkFrame(cell, fg_color="transparent"); pf.pack(side="bottom", fill="x", padx=5, pady=(0, 5))
            pb = ctk.CTkProgressBar(pf, height=8, corner_radius=4); pb.pack(side="left", fill="x", expand=True, padx=(0, 5)); pb.set(0)
            tl = ctk.CTkLabel(pf, text="", font=("Consolas", 11), text_color="gray", width=45, anchor="e"); tl.pack(side="right")
            if pil_image:
                try: ctk.CTkLabel(cell, image=ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(128, 128)), text="").pack(pady=(10, 5))
                except: pass
            ctk.CTkLabel(cell, text=data["titleName"], font=("Arial", 14, "bold"), wraplength=180, justify="center").pack(pady=2)
            ctk.CTkLabel(cell, text=f"{data['titleId']} | FW: {data['requiredSystemSoftwareVersion']}", font=("Arial", 11), text_color="gray", justify="center", wraplength=180).pack(pady=(0, 5))
            if internal_path_label:
                ctk.CTkLabel(cell, text=internal_path_label, font=("Arial", 10), text_color="#888888", justify="center", wraplength=180).pack(pady=(0, 5))
            is_bp, bp_info = self.check_backport_status(data["titleName"], data["titleId"], data["contentVersion"])
            if is_bp:
                stxt = f"Backported ({', '.join(bp_info)})" if bp_info else "Backported"
                scol = "#00FF00"
            else:
                stxt = "Not Backported"
                scol = "#FF0000"
            sl = ctk.CTkLabel(cell, text=stxt, font=("Arial", 12, "bold"), text_color=scol); sl.pack(pady=5)
            opts = self.get_available_fakelib_versions(); fv = tk.StringVar(value=opts[0] if opts else "None"); fav = tk.BooleanVar(value=False)
            fm = ctk.CTkOptionMenu(cell, variable=fv, values=opts, width=100); fm.pack(pady=(5, 2))
            ctk.CTkCheckBox(cell, text="All SDKs", variable=fav).pack(pady=2)
            bf = ctk.CTkFrame(cell, fg_color="transparent"); bf.pack(pady=(5, 10))
            b = ctk.CTkButton(bf, text="Start", width=80, height=28, command=lambda wk=widget_key: self.start_single_backport(wk)); b.pack(side="left", padx=2)
            ctk.CTkButton(bf, text="Open", width=60, height=28, fg_color="transparent", border_width=1, command=lambda wk=widget_key: self.open_backport_folder(wk)).pack(side="left", padx=2)
        else:
            row_f = ctk.CTkFrame(self.scrollable_frame); row_f.pack(fill="x", pady=5, padx=5)
            pf = ctk.CTkFrame(row_f, fg_color="transparent"); pf.pack_forget()
            pb = ctk.CTkProgressBar(pf, height=8, corner_radius=4); pb.pack(side="left", fill="x", expand=True, padx=(10, 5), pady=5); pb.set(0)
            tl = ctk.CTkLabel(pf, text="", font=("Consolas", 11), text_color="gray", width=45, anchor="e"); tl.pack(side="right", padx=(0, 10), pady=5)
            if pil_image:
                try: ctk.CTkLabel(row_f, image=ctk.CTkImage(light_image=pil_image, dark_image=pil_image, size=(64, 64)), text="").pack(side="left", padx=10, pady=10)
                except: pass
            txt_f = ctk.CTkFrame(row_f, fg_color="transparent"); txt_f.pack(side="left", fill="x", expand=True, pady=10)
            ctk.CTkLabel(txt_f, text=data["titleName"], font=("Arial", 16, "bold"), anchor="w").pack(fill="x")
            info_text = f"Title ID: {data['titleId']}\nVersion: {data['contentVersion']} | FW: {data['requiredSystemSoftwareVersion']} | SDK: {data['sdkVersion']}\nContent ID: {data['contentId']}\nSource: {source_type}"
            if internal_path:
                info_text += f"\nArchive Path: {internal_path}"
            ctk.CTkLabel(txt_f, text=info_text, font=("Arial", 12), anchor="w", justify="left").pack(fill="x")
            is_bp, bp_info = self.check_backport_status(data["titleName"], data["titleId"], data["contentVersion"])
            if is_bp:
                stxt = f"Backported ({', '.join(bp_info)})" if bp_info else "Backported"
                scol = "#00FF00"
            else:
                stxt = "Not Backported"
                scol = "#FF0000"
            sl = ctk.CTkLabel(txt_f, text=stxt, font=("Arial", 14, "bold"), text_color=scol, anchor="w"); sl.pack(fill="x", pady=(5, 0))
            btn_f = ctk.CTkFrame(row_f, fg_color="transparent"); btn_f.pack(side="right", padx=10, fill="y")
            opts = self.get_available_fakelib_versions(); fv = tk.StringVar(value=opts[0] if opts else "None"); fav = tk.BooleanVar(value=False)
            fm = ctk.CTkOptionMenu(btn_f, variable=fv, values=opts, width=80); fm.pack(pady=(10, 2))
            ctk.CTkCheckBox(btn_f, text="All SDKs", variable=fav, width=80).pack(pady=(0, 2))
            b = ctk.CTkButton(btn_f, text="Start", width=80, height=28, command=lambda wk=widget_key: self.start_single_backport(wk)); b.pack(pady=(2, 2))
            ctk.CTkButton(btn_f, text="Open Dir", width=80, height=28, fg_color="transparent", border_width=1, command=lambda wk=widget_key: self.open_backport_folder(wk)).pack(pady=(2, 10))
        return pb, sl, b, fv, fav, fm, tl, pf

    def _load_app_settings(self):
        if self.config_dir.joinpath("settings.json").exists():
            try:
                with open(self.config_dir / "settings.json", 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {
            "latest_folder": str(Path.home()), 
            "custom_output_dir": "", 
            "enable_7z": False, 
            "appearance_mode": "dark", 
            "color_theme": "blue", 
            "max_scan_threads": 4, 
            "max_backport_threads": 4, 
            "view_mode": "List"
        }

    def _load_games_cache(self):
        if self.config_dir.joinpath("games.json").exists():
            try:
                with open(self.config_dir / "games.json", 'r', encoding='utf-8') as f: return json.load(f)
            except: pass
        return {}

    def _save_games_cache(self):
        try:
            with open(self.cache_file, 'w', encoding='utf-8') as f: json.dump(self.games_cache, f, indent=4)
        except: pass


if __name__ == "__main__":
    app = App()
    app.mainloop()