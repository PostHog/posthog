#!/usr/bin/env sh
# Runs `eas build` with this app directory as the whole upload.
#
# By default EAS archives the git root: the full monorepo, whose root pnpm workspace
# excludes this app, so the build would install the wrong dependencies. EAS_NO_VCS=1
# alone is not enough, because eas-cli still asks git for the root. An absolute
# EAS_PROJECT_ROOT pins it here, and .easignore filters the archive.
set -eu

app_dir=$(cd "$(dirname "$0")/.." && pwd)

if ! command -v eas >/dev/null 2>&1; then
    echo "eas-cli is not installed. Install it with: npm install -g eas-cli" >&2
    exit 1
fi

EAS_NO_VCS=1 EAS_PROJECT_ROOT="$app_dir" exec eas build "$@"
