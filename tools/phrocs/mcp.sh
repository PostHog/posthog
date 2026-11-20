#!/usr/bin/env bash
# Starts `phrocs mcp` for the MCP client in .mcp.json.
# stdout carries the MCP protocol, so everything else goes to stderr.
set -euo pipefail

phrocs_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# phrocs derives its IPC socket from the working directory, and bin/start runs
# it from the repo root.
cd "$phrocs_dir/../.."

# Rebuild like the flox hook does, so a checkout that moved since the last
# activation still gets the mcp subcommand. GOPROXY=off keeps the network out
# of MCP startup: a missing module fails the build fast, and the binary that is
# already there runs instead.
if command -v go >/dev/null 2>&1; then
    GOPROXY=off make -s -C "$phrocs_dir" build >&2 || echo "phrocs: build failed, using the existing binary" >&2
fi

# A dist build from before the mcp subcommand can outlive a failed rebuild, so
# take the first binary that knows the subcommand.
for candidate in "$phrocs_dir/dist/phrocs" "$(command -v phrocs || true)"; do
    if [[ -x "$candidate" ]] && "$candidate" --help 2>/dev/null | grep -q "phrocs mcp"; then
        exec "$candidate" mcp
    fi
done
echo "phrocs: no phrocs with the mcp subcommand found. Build it with: hogli phrocs:build" >&2
exit 1
