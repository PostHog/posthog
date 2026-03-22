#!/bin/bash
# phrocs installer
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/PostHog/posthog/master/tools/phrocs/install.sh | sh

set -euo pipefail

REPO="PostHog/posthog"
RELEASE_TAG="phrocs-latest"

main() {
    OS="$(uname -s)"
    ARCH="$(uname -m)"

    case "$OS" in
        Linux)  os="linux" ;;
        Darwin) os="darwin" ;;
        *)
            echo "Error: unsupported OS: $OS" >&2
            exit 1
            ;;
    esac

    case "$ARCH" in
        x86_64|amd64)  arch="amd64" ;;
        arm64|aarch64) arch="arm64" ;;
        *)
            echo "Error: unsupported architecture: $ARCH" >&2
            exit 1
            ;;
    esac

    BINARY="phrocs-${os}-${arch}"
    URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/${BINARY}"

    # Determine install directory
    if [ -w /usr/local/bin ]; then
        INSTALL_DIR="/usr/local/bin"
    elif [ -d "$HOME/.local/bin" ]; then
        INSTALL_DIR="$HOME/.local/bin"
    else
        mkdir -p "$HOME/.local/bin"
        INSTALL_DIR="$HOME/.local/bin"
    fi

    CHECKSUMS_URL="https://github.com/${REPO}/releases/download/${RELEASE_TAG}/checksums.txt"
    TMPDIR="$(mktemp -d)"
    trap 'rm -rf "$TMPDIR"' EXIT

    echo "Downloading phrocs for ${os}/${arch}..."
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "${TMPDIR}/phrocs"
        curl -fsSL "$CHECKSUMS_URL" -o "${TMPDIR}/checksums.txt"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "${TMPDIR}/phrocs" "$URL"
        wget -qO "${TMPDIR}/checksums.txt" "$CHECKSUMS_URL"
    else
        echo "Error: curl or wget is required" >&2
        exit 1
    fi

    # Verify checksum
    EXPECTED=$(grep -F " ${BINARY}" "${TMPDIR}/checksums.txt" | awk '{print $1}' || true)
    if [ -z "$EXPECTED" ]; then
        echo "Error: no checksum found for ${BINARY}" >&2
        exit 1
    fi
    if command -v sha256sum >/dev/null 2>&1; then
        ACTUAL=$(sha256sum "${TMPDIR}/phrocs" | awk '{print $1}')
    elif command -v shasum >/dev/null 2>&1; then
        ACTUAL=$(shasum -a 256 "${TMPDIR}/phrocs" | awk '{print $1}')
    else
        echo "Warning: cannot verify checksum (sha256sum/shasum not found), skipping" >&2
        ACTUAL="$EXPECTED"
    fi
    if [ "$ACTUAL" != "$EXPECTED" ]; then
        echo "Error: checksum mismatch (expected ${EXPECTED}, got ${ACTUAL})" >&2
        exit 1
    fi

    cp "${TMPDIR}/phrocs" "${INSTALL_DIR}/phrocs"
    chmod +x "${INSTALL_DIR}/phrocs"

    echo "Installed phrocs to ${INSTALL_DIR}/phrocs"
    "${INSTALL_DIR}/phrocs" --version

    # Warn if install dir is not in PATH
    case ":$PATH:" in
        *":${INSTALL_DIR}:"*) ;;
        *)
            echo ""
            echo "Note: ${INSTALL_DIR} is not in your PATH."
            echo "Add it with: export PATH=\"${INSTALL_DIR}:\$PATH\""
            ;;
    esac
}

main
