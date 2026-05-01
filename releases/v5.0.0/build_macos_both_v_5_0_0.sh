#!/usr/bin/env bash
set -euo pipefail

# Iconik Storage Locator v5_0_0 build script.
#
# Runtime code is Python standard library only. PyInstaller is a build-time
# dependency used only to create standalone macOS executables.

APP_NAME="iconik_locator"
VERSION="5_0_0"
SRC="iconik_locator.py"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST="${ROOT}/dist"
BUILD="${ROOT}/build"
export PYINSTALLER_CONFIG_DIR="${ROOT}/.pyinstaller"

die() { echo "ERROR: $*" >&2; exit 1; }
msg() { echo "== $* =="; }

ensure_pyinstaller() {
  local py="$1"
  "${py}" - <<'PY' >/dev/null 2>&1 || "${py}" -m pip install --upgrade pyinstaller
import PyInstaller  # noqa: F401
PY
}

detect_arm_python() {
  local c
  for c in \
    "${ROOT}/../2_0_3/venv-arm/bin/python" \
    "$(command -v python3 || true)" \
    "/opt/homebrew/bin/python3" \
    "/usr/local/bin/python3"; do
    [[ -x "$c" ]] || continue
    if arch -arm64 "$c" -c 'import platform; print(platform.machine())' 2>/dev/null | grep -q '^arm64$'; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

detect_x86_python() {
  local c
  for c in \
    "${ROOT}/../2_0_3/venv-x86/bin/python" \
    "/usr/local/bin/python3" \
    "$(command -v python3 || true)"; do
    [[ -x "$c" ]] || continue
    if arch -x86_64 "$c" -c 'import platform; print(platform.machine())' 2>/dev/null | grep -q '^x86_64$'; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

sign_if_possible() {
  local bin="$1"
  if command -v codesign >/dev/null 2>&1; then
    codesign --force --sign - "$bin" >/dev/null 2>&1 || true
  fi
}

cd "$ROOT"
[[ -f "$SRC" ]] || die "Source not found: $SRC"

rm -rf "$BUILD" "$DIST"
mkdir -p "$DIST"

ARM_PY="$(detect_arm_python || true)"
[[ -n "$ARM_PY" ]] || die "Could not find an arm64 Python 3. On Apple Silicon, install Homebrew Python or reuse v2_0_3/venv-arm."
msg "arm64 build using: ${ARM_PY}"
ensure_pyinstaller "$ARM_PY"
arch -arm64 "$ARM_PY" -m PyInstaller \
  --onefile \
  --clean \
  --name "${APP_NAME}_${VERSION}_arm64" \
  --distpath "$DIST" \
  --workpath "${BUILD}/${APP_NAME}_${VERSION}_arm64" \
  --specpath "$ROOT" \
  "$SRC"
sign_if_possible "${DIST}/${APP_NAME}_${VERSION}_arm64"
file "${DIST}/${APP_NAME}_${VERSION}_arm64"

X86_PY="$(detect_x86_python || true)"
[[ -n "$X86_PY" ]] || die "Could not find an x86_64 Python 3 under Rosetta. Install Intel Python/Rosetta or reuse v2_0_3/venv-x86."
msg "x86_64 build using: ${X86_PY}"
ensure_pyinstaller "$X86_PY"
arch -x86_64 "$X86_PY" -m PyInstaller \
  --onefile \
  --clean \
  --name "${APP_NAME}_${VERSION}_x86_64" \
  --distpath "$DIST" \
  --workpath "${BUILD}/${APP_NAME}_${VERSION}_x86_64" \
  --specpath "$ROOT" \
  "$SRC"
sign_if_possible "${DIST}/${APP_NAME}_${VERSION}_x86_64"
file "${DIST}/${APP_NAME}_${VERSION}_x86_64"

msg "Packaging"
cd "$DIST"
zip -q -r "${APP_NAME}_${VERSION}_arm64.zip" "${APP_NAME}_${VERSION}_arm64"
zip -q -r "${APP_NAME}_${VERSION}_x86_64.zip" "${APP_NAME}_${VERSION}_x86_64"
shasum -a 256 \
  "${APP_NAME}_${VERSION}_arm64" \
  "${APP_NAME}_${VERSION}_x86_64" \
  "${APP_NAME}_${VERSION}_arm64.zip" \
  "${APP_NAME}_${VERSION}_x86_64.zip" > checksums.txt

msg "Artifacts ready in ${DIST}"
cat <<EOF
Artifacts:
  ${DIST}/${APP_NAME}_${VERSION}_arm64
  ${DIST}/${APP_NAME}_${VERSION}_arm64.zip
  ${DIST}/${APP_NAME}_${VERSION}_x86_64
  ${DIST}/${APP_NAME}_${VERSION}_x86_64.zip

If macOS marks a downloaded file as quarantined:
  xattr -dr com.apple.quarantine "${DIST}/${APP_NAME}_${VERSION}_arm64"
  xattr -dr com.apple.quarantine "${DIST}/${APP_NAME}_${VERSION}_x86_64"
EOF
