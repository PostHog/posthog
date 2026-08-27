#!/usr/bin/env bash
set -euo pipefail

PHROCS_BIN="bin/phrocs"
RELEASE_URL="https://github.com/PostHog/posthog/releases/download/phrocs-latest"

MODE="ensure"
[ "${1:-}" = "--update" ] && MODE="update"

if [ "$MODE" = "update" ] && [ -n "${CI:-}" ]; then
  exit 0
fi

if [ "$MODE" = "ensure" ] && [ -x "$PHROCS_BIN" ]; then
  exit 0
fi

ARCH=$(uname -m)
OS=$(uname -s | tr '[:upper:]' '[:lower:]')

case "$ARCH" in
  arm64|aarch64) ARCH="arm64" ;;
  x86_64)        ARCH="amd64" ;;
  *)             echo "Unsupported architecture: $ARCH" >&2; exit 1 ;;
esac

case "$OS" in
  darwin|linux) ;;
  *)            echo "Unsupported OS: $OS" >&2; exit 1 ;;
esac

BINARY="phrocs-${OS}-${ARCH}"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

bail() {
  if [ -x "$PHROCS_BIN" ]; then
    echo "phrocs: $1, keeping existing binary" >&2
    exit 0
  fi
  echo "phrocs: $1 and no local binary exists" >&2
  if [ "$MODE" = "update" ]; then
    echo "phrocs: will retry on next pnpm install or pnpm dev" >&2
    exit 0
  fi
  exit 1
}

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

curl -fsSL --max-time 10 "${RELEASE_URL}/checksums.txt" -o "$TMP_DIR/checksums.txt" \
  || bail "could not fetch checksums"

EXPECTED=$(awk -v bin="$BINARY" '{name = $2; sub(/^\*/, "", name); if (name == bin) {print $1; exit}}' "$TMP_DIR/checksums.txt")
[ -n "$EXPECTED" ] || bail "no checksum for ${BINARY} in latest release"

if [ -x "$PHROCS_BIN" ] && [ "$(sha256 "$PHROCS_BIN")" = "$EXPECTED" ]; then
  exit 0
fi

echo "phrocs: downloading latest release..."
curl -fsSL --max-time 120 "${RELEASE_URL}/${BINARY}" -o "$TMP_DIR/phrocs" \
  || bail "download failed"

ACTUAL=$(sha256 "$TMP_DIR/phrocs")
if [ "$ACTUAL" != "$EXPECTED" ]; then
  bail "checksum mismatch on download (expected ${EXPECTED}, got ${ACTUAL})"
fi

mkdir -p bin
chmod +x "$TMP_DIR/phrocs"
mv "$TMP_DIR/phrocs" "$PHROCS_BIN"
echo "phrocs: updated to latest (${PHROCS_BIN})"
