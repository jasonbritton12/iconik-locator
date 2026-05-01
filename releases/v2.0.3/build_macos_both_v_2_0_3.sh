#!/usr/bin/env bash
set -euo pipefail

# Iconik Storage Locator build script
# Builds both Apple Silicon (arm64) and Intel (x86_64) macOS binaries
# for iconik_locator v2_0_3 using PyInstaller.

APP_NAME="iconik_locator"
VERSION="2_0_3"
SRC="iconik_locator_tui.py"

# --- helpers ---
die() { echo "ERROR: $*" >&2; exit 1; }
msg() { echo "== $* =="; }

check_rosetta() {
  if ! pgrep -q oahd 2>/dev/null; then
    echo "Rosetta not detected. If the x86_64 build fails, you may need to install it:"
    echo "  softwareupdate --install-rosetta --agree-to-license"
  fi
}

# Try a few likely python3 locations for arm64
detect_arm_python() {
  local c
  for c in "$(command -v python3 || true)" \
           "/opt/homebrew/bin/python3" \
           "/usr/local/bin/python3" \
           "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"; do
    [[ -x "$c" ]] || continue
    if arch -arm64 "$c" -c 'import platform; print(platform.machine())' 2>/dev/null | grep -q '^arm64$'; then
      echo "$c"; return 0
    fi
  done
  return 1
}

# Try a few likely python3 locations for x86_64 under Rosetta
detect_x86_python() {
  local c
  for c in "/usr/local/bin/python3" "$(command -v python3 || true)"; do
    [[ -x "$c" ]] || continue
    if arch -x86_64 "$c" -c 'import platform; print(platform.machine())' 2>/dev/null | grep -q '^x86_64$'; then
      echo "$c"; return 0
    fi
  done
  return 1
}

check_rosetta

rm -rf build dist venv-arm venv-x86 || true
mkdir -p dist

# --- arm64 build ---
ARM_PY="$(detect_arm_python || true)"
[[ -n "${ARM_PY}" ]] || die "Could not find an arm64 Python 3 (e.g., /opt/homebrew/bin/python3 via Homebrew)."
msg "arm64 build using: ${ARM_PY}"
"${ARM_PY}" -m venv venv-arm
source venv-arm/bin/activate
python -m pip install --upgrade pip
python -m pip install pyinstaller requests rich pandas openpyxl
pyinstaller --onefile --name "${APP_NAME}_${VERSION}_arm64" "${SRC}"
deactivate
file "dist/${APP_NAME}_${VERSION}_arm64" || true

# --- x86_64 build ---
X86_PY="$(detect_x86_python || true)"
[[ -n "${X86_PY}" ]] || die "x86_64 Python not found under Rosetta. Install Intel Homebrew + python3 and retry."
msg "x86_64 build using: ${X86_PY}"

# Export variables so the heredoc shell sees them
export APP_NAME VERSION SRC X86_PY

arch -x86_64 /bin/zsh <<'EOS'
set -euo pipefail
PY="$X86_PY"
"$PY" -m venv venv-x86
source venv-x86/bin/activate
python -m pip install --upgrade pip
python -m pip install pyinstaller requests rich pandas openpyxl
pyinstaller --onefile --name "${APP_NAME}_${VERSION}_x86_64" "${SRC}"
deactivate
file "dist/${APP_NAME}_${VERSION}_x86_64" || true
EOS

# --- package & checksums ---
msg "Packaging"
cd dist
zip -r "${APP_NAME}_${VERSION}_arm64.zip" "${APP_NAME}_${VERSION}_arm64" >/dev/null
zip -r "${APP_NAME}_${VERSION}_x86_64.zip" "${APP_NAME}_${VERSION}_x86_64" >/dev/null
shasum -a 256 "${APP_NAME}_${VERSION}_arm64" "${APP_NAME}_${VERSION}_x86_64" \
  "${APP_NAME}_${VERSION}_arm64.zip" "${APP_NAME}_${VERSION}_x86_64.zip" > checksums.txt || true

msg "Artifacts ready in dist/"
echo "If macOS claims a binary is 'damaged', clear quarantine:"
echo "  xattr -dr com.apple.quarantine dist/${APP_NAME}_${VERSION}_arm64"
echo "  xattr -dr com.apple.quarantine dist/${APP_NAME}_${VERSION}_x86_64"