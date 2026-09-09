#!/usr/bin/env bash
# Local Nuitka build helper for Linux / macOS (bash).
# Mirrors the flags used in .github/workflows/release.yml so local builds match CI.
#
# Flags (spec):
#   --standalone --onefile --enable-plugin=pyside6
#   --windows-console-mode=disable --windows-icon-from-ico=src/proxmox_widget/resources/app.ico
#   --include-data-dir=src/proxmox_widget/resources=resources
#
# Usage:
#   bash scripts/build-nuitka.sh              # -> dist/ProxmoxWidget-linux.bin (or macos)
#   bash scripts/build-nuitka.sh --clean      # clean dist first
#   OUTPUT_FILE=dist/MyBuild.bin bash scripts/build-nuitka.sh
#   bash scripts/build-nuitka.sh --windows    # force Windows flags (cross-check)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

ICON_PATH="src/proxmox_widget/resources/app.ico"
ENTRY_POINT="src/proxmox_widget/__main__.py"
DIST_DIR="dist"
OUTPUT_FILE="${OUTPUT_FILE:-}"
CLEAN=0
FORCE_WINDOWS=0

for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --windows) FORCE_WINDOWS=1 ;;
    --help|-h)
      echo "Usage: $0 [--clean] [--windows] [OUTPUT_FILE]"
      echo "  --clean    Remove dist/ before build"
      echo "  --windows  Force Windows flags (for testing)"
      exit 0
      ;;
    *)
      # bare arg treated as output file
      if [[ "$arg" != --* ]]; then
        OUTPUT_FILE="$arg"
      fi
      ;;
  esac
done

if [[ -z "$OUTPUT_FILE" ]]; then
  case "$(uname -s)" in
    Darwin) OUTPUT_FILE="ProxmoxWidget-macos.bin" ;;
    *)      OUTPUT_FILE="ProxmoxWidget-linux.bin" ;;
  esac
fi

# Also allow positional OUTPUT_FILE override via env
if [[ -n "${1:-}" && "${1:-}" != --* ]]; then
  OUTPUT_FILE="$1"
fi

if [[ ! -f "$ENTRY_POINT" ]]; then
  echo "ERROR: Entry point not found: $ENTRY_POINT (run from repo root)" >&2
  exit 1
fi

HAS_ICON=0
if [[ -f "$ICON_PATH" ]]; then
  HAS_ICON=1
else
  echo "WARN: Icon not found at $ICON_PATH — build will continue without --windows-icon-from-ico" >&2
fi

if [[ "$CLEAN" -eq 1 && -d "$DIST_DIR" ]]; then
  echo "Cleaning $DIST_DIR..."
  rm -rf "$DIST_DIR"
fi
mkdir -p "$DIST_DIR"

echo "Checking Python deps..."
python3 -m pip install --upgrade pip
pip install -e .
pip install nuitka ordered-set

# Base Nuitka flags (always)
NUITKA_ARGS=(
  --standalone
  --onefile
  --enable-plugin=pyside6
  --include-data-dir=src/proxmox_widget/resources=resources
)

# Windows-only flags (only on Windows or when --windows forced)
if [[ "$FORCE_WINDOWS" -eq 1 ]]; then
  NUITKA_ARGS+=(--windows-console-mode=disable)
  if [[ "$HAS_ICON" -eq 1 ]]; then
    NUITKA_ARGS+=(--windows-icon-from-ico="$ICON_PATH")
  fi
elif [[ "$(uname -s)" == MINGW* || "$(uname -s)" == MSYS* || "$(uname -s)" == CYGWIN* ]]; then
  # Git Bash on Windows
  NUITKA_ARGS+=(--windows-console-mode=disable)
  if [[ "$HAS_ICON" -eq 1 ]]; then
    NUITKA_ARGS+=(--windows-icon-from-ico="$ICON_PATH")
  fi
fi

NUITKA_ARGS+=(
  --output-filename="$OUTPUT_FILE"
  --output-dir="$DIST_DIR"
  "$ENTRY_POINT"
)

echo "Running: python -m nuitka ${NUITKA_ARGS[*]}"
python -m nuitka "${NUITKA_ARGS[@]}"

BUILT="$DIST_DIR/$OUTPUT_FILE"
if [[ -f "$BUILT" ]]; then
  SIZE=$(du -h "$BUILT" | cut -f1)
  echo "Build OK: $BUILT ($SIZE)"
  # SHA256
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$BUILT" > "$BUILT.sha256"
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$BUILT" > "$BUILT.sha256"
  else
    python3 -c "import hashlib,pathlib; p=pathlib.Path('$BUILT'); h=hashlib.sha256(p.read_bytes()).hexdigest(); open('$BUILT.sha256','w').write(f'{h}  $OUTPUT_FILE\n')"
  fi
  cat "$BUILT.sha256"
  echo "Checksum: $BUILT.sha256"
  ls -lh "$DIST_DIR"
else
  echo "ERROR: Build finished but $BUILT not found" >&2
  exit 1
fi
