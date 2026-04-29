# MCP Server Scripts

Scripts for connecting AI assistants (Claude Code, Cursor, etc.) to PostHog's internal Grafana instances via the [Grafana MCP server](https://github.com/grafana/mcp-grafana).

## Why these scripts exist

PostHog's Grafana instances are reachable directly over Tailscale at plain HTTP hostnames
(`grafana-prod-us`, `grafana-prod-eu`, `grafana-dev`).
Authentication is handled at the Grafana layer via a service account Bearer token,
which the Grafana MCP server supports natively.

These scripts glue that together:

1. Resolve the right Tailscale hostname for the selected region
2. Pull the service account token from macOS Keychain
3. Hand both to `mcp-grafana`

## Prerequisites

- **Tailscale** connected, with access to the PostHog tailnet (hostnames `grafana-prod-us`, `grafana-prod-eu`, `grafana-dev` must resolve)
- **mcp-grafana** binary installed
- **macOS** (for Keychain-based token storage) or Linux with environment variables

### Installing mcp-grafana

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest
```

Make sure `$GOPATH/bin` (usually `~/go/bin`) is in your PATH.

## Setup

### 1. Create Grafana service account tokens

For each region you need access to, create a service account token in Grafana:

1. Go to **Administration > Service accounts**
2. Create a new service account (or use an existing one)
3. Add a token with appropriate permissions (typically Viewer or Editor)
4. Copy the token

### 2. Add scripts to your PATH

Add the following to your shell config file (`~/.zshrc`, `~/.bashrc`, or equivalent):

```bash
# PostHog infra scripts (grafana-region, grafana-token, etc.)
export PATH="$HOME/dev/posthog/posthog/tools/infra-scripts/mcp:$PATH"
```

Adjust the path if your PostHog repo is in a different location. Then reload your shell:

```bash
source ~/.zshrc  # or ~/.bashrc
```

### 3. Store tokens in Keychain (macOS)

```bash
grafana-token us <your-us-token>
grafana-token eu <your-eu-token>
grafana-token dev <your-dev-token>  # optional
```

### 4. Configure your MCP client

Add the wrapper script to your MCP client configuration. See the [Usage](#usage) section for single-server and multi-server configuration examples.

For a basic single-server setup, add to your MCP settings (`~/.config/claude-code/.mcp.json` for Claude Code, or your editor's MCP config):

```json
{
  "mcpServers": {
    "grafana": {
      "command": "/Users/YOUR_USERNAME/dev/posthog/posthog/tools/infra-scripts/mcp/mcp-grafana-wrapper.sh",
      "args": []
    }
  }
}
```

## Usage

### Region selection

The wrapper script determines which Grafana region to connect to using (in order of precedence):

1. **`GRAFANA_REGION` env var** — set in your MCP client config (recommended for multi-server setups)
2. **`~/.grafana-region` file** — set via the `grafana-region` command
3. **Default** — `us` if neither is set

Region → host mapping:

| Region | Tailscale host           |
| ------ | ------------------------ |
| `us`   | `http://grafana-prod-us` |
| `eu`   | `http://grafana-prod-eu` |
| `dev`  | `http://grafana-dev`     |

#### Single-server setup (switching regions manually)

Use the `grafana-region` command to switch between PostHog environments:

```bash
grafana-region          # Show current region
grafana-region us       # Switch to prod-us (us-east-1)
grafana-region eu       # Switch to prod-eu (eu-central-1)
grafana-region dev      # Switch to dev environment
```

**Important: Restart required after switching regions**

MCP servers are initialized once when your AI assistant starts. The region is read at startup, so changing the region while the assistant is running has no effect until you restart.

To restart and apply the new region:

- **Claude Code**: Type `/exit` to quit, then restart Claude Code
- **Cursor**: Close and reopen the editor, or restart the MCP server from settings
- **VS Code**: Reload the window (`Cmd+Shift+P` → "Developer: Reload Window")

#### Multi-server setup (both regions simultaneously)

Run two MCP server instances with the `GRAFANA_REGION` env var so both regions are available without restarting.
You can also use `-disable-*` flags to reduce the tool surface per server (see `mcp-grafana --help` for the full list).

##### Claude Code

Add to `~/.config/claude-code/.mcp.json`:

```json
{
  "mcpServers": {
    "grafana": {
      "command": "/Users/YOUR_USERNAME/dev/posthog/posthog/tools/infra-scripts/mcp/mcp-grafana-wrapper.sh",
      "args": ["-disable-admin", "-disable-alerting", "-disable-incident", "-disable-oncall"],
      "env": { "GRAFANA_REGION": "us" }
    },
    "grafana-eu": {
      "command": "/Users/YOUR_USERNAME/dev/posthog/posthog/tools/infra-scripts/mcp/mcp-grafana-wrapper.sh",
      "args": ["-disable-admin", "-disable-alerting", "-disable-incident", "-disable-oncall"],
      "env": { "GRAFANA_REGION": "eu" }
    }
  }
}
```

#### Migrating from single-server to multi-server

If you already have a single `grafana` server configured with both US and EU tokens in Keychain, run the migration script:

```bash
grafana-migrate-multi            # migrate with confirmation prompt
grafana-migrate-multi --dry-run  # preview changes without writing
grafana-migrate-multi --slim     # also normalize to recommended (smaller) disable-flag set
```

The script:

1. Pins `GRAFANA_REGION=us` on your existing `grafana` entry
2. Adds a `grafana-eu` entry (clone of `grafana` with `GRAFANA_REGION=eu`)
3. Duplicates your `mcp__grafana__*` permissions for `mcp__grafana-eu__*` in `~/.claude/settings.json`

With `--slim`, it also replaces the `args` on both entries with the recommended set (`-disable-admin`, `-disable-alerting`, `-disable-incident`, `-disable-oncall`), removing any extra disable flags you may have accumulated.

Backups of modified files are saved with a `.bak` extension.
After migrating, restart your MCP client. The `grafana-region` command is no longer needed since each server has its region pinned via env var.

### Checking token status

```bash
grafana-token           # Show status of all tokens
grafana-token us        # Check if US token is configured
```

## Linux support

On Linux, Keychain is not available. Instead, set the `GRAFANA_SERVICE_ACCOUNT_TOKEN` environment variable before starting your MCP client:

```bash
export GRAFANA_SERVICE_ACCOUNT_TOKEN="your-token-here"
```

You may want to use a secrets manager or encrypted file for production use.

## Troubleshooting

### Hostname doesn't resolve / connection refused

The Tailscale hostnames (`grafana-prod-us`, `grafana-prod-eu`, `grafana-dev`) only resolve when Tailscale is connected to the PostHog tailnet. Check with:

```bash
tailscale status
```

If you're not connected, run `tailscale up` (or open the Tailscale app) and ensure you're logged into the PostHog tailnet.

### "mcp-grafana not found"

Install it with:

```bash
go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest
```

Or set `MCP_GRAFANA_BIN` to the full path of the binary.

### "Could not retrieve token from keychain"

Store your token first:

```bash
grafana-token us <your-token>
```

### 401 Unauthorized from Grafana

Your service account token may have been revoked or expired. Create a new one in Grafana (Administration > Service accounts) and store it:

```bash
grafana-token us <new-token>
```

Then restart your MCP client.

## Available Grafana MCP tools

Once connected, you'll have access to Grafana MCP tools including:

- Dashboard search and retrieval
- Prometheus/Loki querying
- Alert rule listing
- Incident management
- On-call schedule viewing

See the [mcp-grafana documentation](https://github.com/grafana/mcp-grafana) for the full list of available tools.
