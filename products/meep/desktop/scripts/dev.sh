#!/bin/sh
# Run the desktop app in development with hot reloading.
#
#   sh scripts/dev.sh            your usual Meep data; US and EU sign-in
#   sh scripts/dev.sh --local    local PostHog with isolated data (needs MEEP_DEV_DIR)
#
# Edits to render code apply to the open window. Structural changes such as new
# types, fields or functions need a rebuild: press r in this terminal.
set -eu
[ ! -x "${HOME}/.cargo/bin/rustup" ] || PATH="${HOME}/.cargo/bin:$PATH"
export PATH
cd "$(dirname "$0")/.."

if ! command -v dx >/dev/null 2>&1; then
    printf '%s\n' 'Hot reloading needs the Dioxus CLI 0.7: cargo install dioxus-cli --version "^0.7"' >&2
    exit 127
fi

if [ "${1:-}" = "--local" ]; then
    shift
    if [ -z "${MEEP_DEV_DIR:-}" ]; then
        printf '%s\n' 'Set MEEP_DEV_DIR to an absolute directory for the local PostHog data (see apps/meep/README.md).' >&2
        exit 2
    fi
    export MEEP_POSTHOG_LOCAL=1
    curl -fsS http://localhost:8010/_health >/dev/null 2>&1 ||
        printf '%s\n' 'Local PostHog is not answering at http://localhost:8010.' >&2
fi

running=$(pgrep -f 'dx serve --hot-patch -p meep ' | tr '\n' ' ' || true)
if [ -n "$running" ]; then
    printf 'Meep already runs under dx serve (PID %s). Use that one, or stop it first: kill %s\n' \
        "${running% }" "${running% }" >&2
    exit 1
fi

unset RUSTC_WRAPPER
exec dx serve --hot-patch -p meep --bin meep --platform macos \
    --features hot-reload "$@"
