#!/usr/bin/env bash
# Wrapper script for mcp-grafana that connects to PostHog Grafana via Tailscale.
#
# PostHog's Grafana instances are reachable over Tailscale at plain HTTP hostnames
# (grafana-prod-us, grafana-prod-eu, grafana-dev). This wrapper looks up a service
# account token from macOS Keychain and hands both the URL and token to mcp-grafana.
#
# Supports switching between prod-us, prod-eu, and dev regions via GRAFANA_REGION env var
# or ~/.grafana-region file (env var takes precedence). Use `grafana-region us`,
# `grafana-region eu`, or `grafana-region dev` to switch, then restart your MCP client.
#
# Prerequisites:
#   - Tailscale connected (grafana-prod-us / grafana-prod-eu / grafana-dev must resolve)
#   - mcp-grafana binary installed (go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest)
#   - Grafana service account token stored in macOS Keychain (see grafana-token script)

set -euo pipefail

# Region configuration
REGION_FILE="$HOME/.grafana-region"
DEFAULT_REGION="us"

# Read current region (default to us if file missing or empty)
if [ -f "$REGION_FILE" ] && [ -s "$REGION_FILE" ]; then
    CURRENT_REGION=$(head -n1 "$REGION_FILE" | tr -cd '[:alnum:]')
else
    CURRENT_REGION="$DEFAULT_REGION"
fi

# Environment variable takes precedence over region file
REGION_SOURCE="$REGION_FILE"
if [ -n "${GRAFANA_REGION:-}" ]; then
    CURRENT_REGION="$GRAFANA_REGION"
    REGION_SOURCE="GRAFANA_REGION env var"
fi

# Validate region
if [[ "$CURRENT_REGION" != "us" && "$CURRENT_REGION" != "eu" && "$CURRENT_REGION" != "dev" ]]; then
    echo "Error: Invalid region '$CURRENT_REGION' from $REGION_SOURCE. Must be 'us', 'eu', or 'dev'." >&2
    exit 1
fi

# Region-specific configuration
case "$CURRENT_REGION" in
    us)
        GRAFANA_HOST="grafana-prod-us"
        KEYCHAIN_SERVICE="grafana-service-account-token-us"
        ;;
    eu)
        GRAFANA_HOST="grafana-prod-eu"
        KEYCHAIN_SERVICE="grafana-service-account-token-eu"
        ;;
    dev)
        GRAFANA_HOST="grafana-dev"
        KEYCHAIN_SERVICE="grafana-service-account-token-dev"
        ;;
esac

# Find mcp-grafana binary
if [ -n "${MCP_GRAFANA_BIN:-}" ]; then
    MCP_GRAFANA="$MCP_GRAFANA_BIN"
elif command -v mcp-grafana &> /dev/null; then
    MCP_GRAFANA="mcp-grafana"
else
    echo "Error: mcp-grafana not found." >&2
    echo "Install it with: go install github.com/grafana/mcp-grafana/cmd/mcp-grafana@latest" >&2
    echo "Or set MCP_GRAFANA_BIN environment variable to the binary path." >&2
    exit 1
fi

# Get the service account token from keychain (macOS only)
if [[ "$OSTYPE" == "darwin"* ]]; then
    export GRAFANA_SERVICE_ACCOUNT_TOKEN="$(security find-generic-password -a "$USER" -s "$KEYCHAIN_SERVICE" -w 2>/dev/null)"
else
    # On Linux, fall back to environment variable
    if [ -z "${GRAFANA_SERVICE_ACCOUNT_TOKEN:-}" ]; then
        echo "Error: GRAFANA_SERVICE_ACCOUNT_TOKEN environment variable not set." >&2
        echo "On Linux, set this variable to your Grafana service account token." >&2
        exit 1
    fi
fi

if [ -z "$GRAFANA_SERVICE_ACCOUNT_TOKEN" ]; then
    echo "Error: Could not retrieve $KEYCHAIN_SERVICE from keychain" >&2
    echo "Add it with: grafana-token $CURRENT_REGION <your-token>" >&2
    exit 1
fi

# Point mcp-grafana at the Tailscale-reachable Grafana host
export GRAFANA_URL="http://$GRAFANA_HOST"

exec "$MCP_GRAFANA" "$@"
