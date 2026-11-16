#!/usr/bin/env bash
# Starts `phrocs mcp` for the MCP client in .mcp.json.
# stdout carries the MCP protocol, so everything else goes to stderr.
set -euo pipefail

phrocs_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# phrocs derives its IPC socket from the working directory, and bin/start runs
# it from the repo root.
cd "$phrocs_dir/../.."

# Rebuild like the flox hook does, so a checkout that moved since the last
# activation still gets the mcp subcommand. A failed build falls back to the
# binary that is already there.
if command -v go >/dev/null 2>&1; then
    make -s -C "$phrocs_dir" build >&2 || echo "phrocs: build failed, using the existing binary" >&2
fi

if [[ -x "$phrocs_dir/dist/phrocs" ]]; then
    exec "$phrocs_dir/dist/phrocs" mcp
fi
if command -v phrocs >/dev/null 2>&1; then
    exec phrocs mcp
fi
echo "phrocs: no binary found. Build it with: hogli phrocs:build" >&2
exit 1
