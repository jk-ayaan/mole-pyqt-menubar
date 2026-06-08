#!/bin/bash
# Build and install the PyQt6 Mole menu bar app for the current user.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Mole Menu"
APP_BUNDLE="${APP_BUNDLE:-$HOME/Applications/${APP_NAME}.app}"
VENV_DIR="${MOLE_MENUBAR_VENV:-$ROOT_DIR/.venv-menubar}"
PYTHON_BIN="${PYTHON:-python3}"
OPEN_APP=true
ENABLE_AUTOSTART=false
BUILD_GO=true

usage() {
    cat <<USAGE
Usage: scripts/install-menubar-app.sh [options]

Options:
  --no-open          Build the app without launching it.
  --autostart       Enable login autostart after installing.
  --no-go-build     Skip building Mole's Go helper binaries.
  --app-bundle PATH Install the app bundle at PATH.
  --venv PATH       Use PATH for the Python virtual environment.
  -h, --help        Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-open)
            OPEN_APP=false
            ;;
        --autostart)
            ENABLE_AUTOSTART=true
            ;;
        --no-go-build)
            BUILD_GO=false
            ;;
        --app-bundle)
            shift
            APP_BUNDLE="${1:?missing app bundle path}"
            ;;
        --venv)
            shift
            VENV_DIR="${1:?missing venv path}"
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Mole Menu is a macOS menu bar app." >&2
    exit 1
fi

mkdir -p "$(dirname "$APP_BUNDLE")" "$ROOT_DIR/dist"

echo "Creating Python environment at $VENV_DIR"
"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$ROOT_DIR/requirements-gui.txt"

if [[ "$BUILD_GO" == "true" ]]; then
    if command -v go > /dev/null 2>&1; then
        make -C "$ROOT_DIR" build
    else
        echo "Go was not found. Install Go and run 'make build' for status/analyze JSON support." >&2
    fi
fi

echo "Creating app bundle at $APP_BUNDLE"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"

cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>MoleMenu</string>
  <key>CFBundleIdentifier</key>
  <string>io.github.mole.pyqt-menubar</string>
  <key>CFBundleName</key>
  <string>Mole Menu</string>
  <key>CFBundleDisplayName</key>
  <string>Mole Menu</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

cat > "$APP_BUNDLE/Contents/MacOS/MoleMenu" <<LAUNCHER
#!/bin/bash
set -euo pipefail
export MOLE_MENUBAR_ROOT="$ROOT_DIR"
export MOLE_MENUBAR_LAUNCHER="\$0"
export PYTHONPATH="$ROOT_DIR/gui\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$VENV_DIR/bin/python" -m mole_menubar --mole-root "$ROOT_DIR"
LAUNCHER

chmod +x "$APP_BUNDLE/Contents/MacOS/MoleMenu"

if [[ "$ENABLE_AUTOSTART" == "true" ]]; then
    PYTHONPATH="$ROOT_DIR/gui${PYTHONPATH:+:$PYTHONPATH}" "$VENV_DIR/bin/python" -m mole_menubar.autostart \
        --enable \
        --launcher "$APP_BUNDLE/Contents/MacOS/MoleMenu"
fi

if [[ "$OPEN_APP" == "true" ]]; then
    /usr/bin/open -gj "$APP_BUNDLE"
fi

echo "Installed $APP_NAME at $APP_BUNDLE"
