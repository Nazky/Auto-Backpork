#!/bin/bash
set -euo pipefail

# ============================================
# Auto-Backpork GUI - Smart Launcher
# ============================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

ARCH=$(uname -m)

echo -e "${CYAN}======================================${NC}"
echo -e "${GREEN}Auto-Backpork GUI - Launcher${NC}"
echo -e "${CYAN}======================================${NC}"

# ============================================
# Helper: check if we can skip setup
# ============================================
quick_launch_possible() {
    if [ -d "venv" ] && [ -f "venv/bin/activate" ] && [ -f "venv/bin/python3" ]; then
        # Test essential modules in the venv
        if venv/bin/python3 -c "import customtkinter, PIL, py7zr, rarfile, _tkinter" 2>/dev/null; then
            return 0
        fi
    fi
    return 1
}

# ============================================
# Quick Launch (skip all setup)
# ============================================
quick_launch() {
    echo -e "${GREEN}✓ Existing environment found. Launching directly...${NC}"
    source venv/bin/activate

    GUI_FILE=""
    if [ -f "gui.py" ]; then
        GUI_FILE="gui.py"
    else
        GUI_FILE=$(find . -name "gui.py" -type f | head -1)
        if [ -z "$GUI_FILE" ]; then
            echo -e "${RED}✗ gui.py not found${NC}"
            exit 1
        fi
    fi

    echo -e "${MAGENTA}Launching Auto-Backpork GUI...${NC}"
    python3 "$GUI_FILE"
    exit $?
}

# ============================================
# OS Detection
# ============================================
detect_os() {
    case "$OSTYPE" in
        darwin*)
            OS_TYPE="macos"
            echo -e "${GREEN}✓ macOS${NC}"
            ;;
        linux-gnu*)
            OS_TYPE="linux"
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                DISTRO=$ID
                echo -e "${GREEN}✓ Linux: ${YELLOW}$NAME${NC}"
            else
                DISTRO="unknown"
            fi
            ;;
        msys*|cygwin*|win32*)
            OS_TYPE="windows"
            echo -e "${GREEN}✓ Windows (Bash)${NC}"
            ;;
        *)
            echo -e "${RED}✗ Unknown OS: $OSTYPE${NC}"
            exit 1
            ;;
    esac
}

# ============================================
# Package Manager Detection
# ============================================
detect_package_manager() {
    if command -v apt-get &>/dev/null; then
        PM="apt"
        PM_INSTALL="sudo apt-get install -y"
        PM_UPDATE="sudo apt-get update"
    elif command -v dnf &>/dev/null; then
        PM="dnf"
        PM_INSTALL="sudo dnf install -y"
        PM_UPDATE="sudo dnf check-update"
    elif command -v yum &>/dev/null; then
        PM="yum"
        PM_INSTALL="sudo yum install -y"
        PM_UPDATE="sudo yum check-update"
    elif command -v pacman &>/dev/null; then
        PM="pacman"
        PM_INSTALL="sudo pacman -S --noconfirm"
        PM_UPDATE="sudo pacman -Sy"
    elif command -v zypper &>/dev/null; then
        PM="zypper"
        PM_INSTALL="sudo zypper install -y"
        PM_UPDATE="sudo zypper refresh"
    elif command -v apk &>/dev/null; then
        PM="apk"
        PM_INSTALL="sudo apk add"
        PM_UPDATE="sudo apk update"
    elif command -v emerge &>/dev/null; then
        PM="emerge"
        PM_INSTALL="sudo emerge"
        PM_UPDATE="sudo emerge --sync"
    elif command -v brew &>/dev/null; then
        PM="brew"
        PM_INSTALL="brew install"
        PM_UPDATE="brew update"
    else
        PM=""
        echo -e "${YELLOW}⚠ No package manager detected.${NC}"
    fi

    [ -n "$PM" ] && echo -e "${GREEN}✓ Package Manager: ${YELLOW}$PM${NC}"
}

# ============================================
# Ensure sudo available (only when needed)
# ============================================
require_sudo() {
    if [[ "$OS_TYPE" == "linux" ]]; then
        if ! command -v sudo &>/dev/null && [ "$EUID" -ne 0 ]; then
            echo -e "${RED}✗ sudo not found and not running as root.${NC}"
            echo -e "${YELLOW}Please install sudo or run as root to install dependencies.${NC}"
            exit 1
        fi
        sudo -v 2>/dev/null || true
    fi
}

# ============================================
# Find a Python with working tkinter
# ============================================
find_working_python() {
    # Check current python3
    if command -v python3 &>/dev/null && python3 -c "import _tkinter" 2>/dev/null; then
        echo "python3"
        return 0
    fi

    # On Linux, try system Python explicitly
    if [[ "$OS_TYPE" == "linux" ]]; then
        for py in /usr/bin/python3 /usr/local/bin/python3; do
            if [ -x "$py" ] && "$py" -c "import _tkinter" 2>/dev/null; then
                echo "$py"
                return 0
            fi
        done
    fi

    # On macOS, check if python-tk is needed
    if [[ "$OS_TYPE" == "macos" ]]; then
        echo -e "${YELLOW}Python lacks tkinter. Will attempt to install python-tk via Homebrew.${NC}"
        return 1
    fi

    return 1
}

# ============================================
# Python Check & Install
# ============================================
check_python() {
    echo -e "${YELLOW}Checking for Python with tkinter support...${NC}"

    WORKING_PYTHON=$(find_working_python) || true

    if [ -z "$WORKING_PYTHON" ]; then
        echo -e "${RED}✗ No Python with tkinter found.${NC}"
        if [ -n "$PM" ]; then
            echo -e "${YELLOW}Installing Python 3 and tkinter...${NC}"
            case $PM in
                apt)      $PM_UPDATE && $PM_INSTALL python3 python3-pip python3-venv python3-tk ;;
                dnf|yum)  $PM_INSTALL python3 python3-pip python3-tkinter ;;
                pacman)   $PM_INSTALL python python-pip tk ;;
                zypper)   $PM_INSTALL python3 python3-pip python3-tk ;;
                apk)      $PM_INSTALL python3 py3-pip py3-tkinter ;;
                emerge)   $PM_INSTALL dev-lang/python:3.9 dev-python/pip ;;
                brew)     brew install python-tk ;;
                *)
                    echo -e "${RED}Please install Python 3.7+ with tkinter manually.${NC}"
                    exit 1
                    ;;
            esac
            # Re-check after installation
            WORKING_PYTHON=$(find_working_python) || {
                echo -e "${RED}Failed to install tkinter.${NC}"
                echo -e "${YELLOW}Try running: sudo apt-get install python3-tk (or equivalent)${NC}"
                exit 1
            }
        else
            exit 1
        fi
    fi

    # Set PYTHON_CMD to the working interpreter
    PYTHON_CMD="$WORKING_PYTHON"
    PY_VER=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
    echo -e "${GREEN}✓ Using Python $PY_VER ($PYTHON_CMD)${NC}"

    # Version check
    MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 7 ]; }; then
        echo -e "${RED}✗ Python 3.7+ required (found $PY_VER)${NC}"
        exit 1
    fi

    # Ensure venv module
    if ! $PYTHON_CMD -m venv --help &>/dev/null; then
        echo -e "${YELLOW}Installing venv module...${NC}"
        case $PM in
            apt)      $PM_INSTALL python3-venv ;;
            dnf|yum)  $PM_INSTALL python3-venv ;;
            apk)      $PM_INSTALL py3-venv ;;
            *)        echo -e "${RED}Please install python3-venv manually.${NC}"; exit 1 ;;
        esac
    fi
}

# ============================================
# Install 7-Zip (p7zip)
# ============================================
install_7zip() {
    echo -e "${YELLOW}Checking for 7-Zip (p7zip)...${NC}"

    # Check if already installed (command may be '7z', '7za', or '7zz')
    if command -v 7z &>/dev/null || command -v 7za &>/dev/null || command -v 7zz &>/dev/null; then
        echo -e "${GREEN}✓ 7-Zip already installed${NC}"
        return 0
    fi

    echo -e "${YELLOW}7-Zip not found. Installing...${NC}"

    if [[ "$OS_TYPE" == "macos" ]]; then
        # macOS: ensure Homebrew is available
        if ! command -v brew &>/dev/null; then
            echo -e "${YELLOW}Installing Homebrew...${NC}"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null
        fi
        brew install p7zip || brew install sevenzip || echo -e "${YELLOW}⚠ 7-Zip install failed${NC}"
    elif [[ "$OS_TYPE" == "linux" ]]; then
        case $PM in
            apt)      $PM_UPDATE && $PM_INSTALL p7zip-full ;;
            dnf|yum)  $PM_INSTALL p7zip p7zip-plugins ;;
            pacman)   $PM_INSTALL p7zip ;;
            zypper)   $PM_INSTALL p7zip-full ;;
            apk)      $PM_INSTALL p7zip ;;
            emerge)   $PM_INSTALL app-arch/p7zip ;;
            brew)     brew install p7zip ;;
            *)
                echo -e "${YELLOW}⚠ Unknown package manager. Please install p7zip manually.${NC}"
                ;;
        esac
    fi

    if command -v 7z &>/dev/null || command -v 7za &>/dev/null; then
        echo -e "${GREEN}✓ 7-Zip installed successfully${NC}"
    else
        echo -e "${YELLOW}⚠ 7-Zip may not be fully installed. 7z archive support may be limited.${NC}"
    fi
}

# ============================================
# System Dependencies (image libs)
# ============================================
install_system_deps() {
    echo -e "${YELLOW}Checking system dependencies...${NC}"

    # Image libraries (Linux only)
    if [[ "$OS_TYPE" == "linux" ]]; then
        case $PM in
            apt)      $PM_INSTALL libjpeg-dev zlib1g-dev libpng-dev ;;
            dnf|yum)  $PM_INSTALL libjpeg-turbo-devel libpng-devel ;;
            pacman)   $PM_INSTALL libjpeg-turbo libpng ;;
            zypper)   $PM_INSTALL libjpeg-turbo-devel libpng-devel ;;
            apk)      $PM_INSTALL libjpeg-turbo-dev zlib-dev libpng-dev ;;
        esac
        echo -e "${GREEN}✓ Image libraries${NC}"
    fi
}

# ============================================
# RAR Support (unrar binary + rarfile module)
# ============================================
install_rar_support() {
    echo -e "${YELLOW}Setting up RAR support...${NC}"

    if [[ "$OS_TYPE" == "macos" ]]; then
        if ! command -v brew &>/dev/null; then
            echo -e "${YELLOW}Installing Homebrew...${NC}"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            eval "$(/opt/homebrew/bin/brew shellenv)" 2>/dev/null || eval "$(/usr/local/bin/brew shellenv)" 2>/dev/null
        fi
        brew install rar || echo -e "${YELLOW}⚠ unrar install failed${NC}"
    elif [[ "$OS_TYPE" == "linux" ]]; then
        case $PM in
            apt)      $PM_UPDATE && $PM_INSTALL unrar ;;
            dnf|yum)  $PM_INSTALL unrar ;;
            pacman)   $PM_INSTALL unrar ;;
            zypper)   $PM_INSTALL unrar ;;
            apk)      $PM_INSTALL unrar ;;
            emerge)   $PM_INSTALL app-arch/unrar ;;
            brew)     brew install rar ;;
            *)        echo -e "${YELLOW}⚠ Cannot install unrar automatically.${NC}" ;;
        esac

        if ! command -v unrar &>/dev/null; then
            echo -e "${YELLOW}Attempting binary download...${NC}"
            local URL=""
            [[ "$ARCH" == "x86_64" ]] && URL="https://www.rarlab.com/rar/rarlinux-x64-6.12.tar.gz"
            [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]] && URL="https://www.rarlab.com/rar/rarlinux-arm64-6.12.tar.gz"
            if [ -n "$URL" ]; then
                (command -v wget &>/dev/null && wget -q "$URL" -O /tmp/rarlinux.tar.gz) ||
                (command -v curl &>/dev/null && curl -sL "$URL" -o /tmp/rarlinux.tar.gz)
                if [ -f /tmp/rarlinux.tar.gz ]; then
                    sudo mkdir -p /usr/local/rar
                    sudo tar -xzf /tmp/rarlinux.tar.gz -C /usr/local/
                    sudo ln -sf /usr/local/rar/unrar /usr/local/bin/unrar
                    rm -f /tmp/rarlinux.tar.gz
                fi
            fi
        fi
    fi

    command -v unrar &>/dev/null && echo -e "${GREEN}✓ unrar${NC}" || echo -e "${YELLOW}⚠ unrar not found${NC}"
}

# ============================================
# Virtual Environment & Python Packages
# ============================================
setup_venv() {
    echo -e "${YELLOW}Creating virtual environment using $PYTHON_CMD...${NC}"
    [ -d "venv" ] && rm -rf venv
    $PYTHON_CMD -m venv venv
    source venv/bin/activate

    pip install --upgrade pip
    echo -e "${YELLOW}Installing Python packages...${NC}"
    pip install customtkinter Pillow py7zr rarfile || {
        echo -e "${YELLOW}Retrying with --no-cache-dir...${NC}"
        pip install --no-cache-dir customtkinter Pillow py7zr rarfile
    }
    echo -e "${GREEN}✓ Python packages installed${NC}"
}

# ============================================
# Launch GUI
# ============================================
launch_gui() {
    source venv/bin/activate
    GUI_FILE=""
    [ -f "gui.py" ] && GUI_FILE="gui.py" || GUI_FILE=$(find . -name "gui.py" -type f | head -1)
    if [ -z "$GUI_FILE" ]; then
        echo -e "${RED}✗ gui.py not found${NC}"
        exit 1
    fi

    echo -e "${MAGENTA}======================================${NC}"
    echo -e "${GREEN}Launching Auto-Backpork GUI...${NC}"
    echo -e "${MAGENTA}======================================${NC}"
    python3 "$GUI_FILE"
}

# ============================================
# Main Execution
# ============================================
main() {
    detect_os
    detect_package_manager

    if quick_launch_possible; then
        quick_launch
    fi

    echo -e "${YELLOW}First run detected. Proceeding with setup...${NC}"
    echo -e "${YELLOW}You may be prompted for your password to install system packages.${NC}"

    require_sudo
    check_python
    install_system_deps
    install_7zip
    install_rar_support
    setup_venv
    launch_gui
}

main "$@"
