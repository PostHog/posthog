#!/usr/bin/env bash
#
# Load PostHog Code (Tasks) local env into the current shell, then restart the
# stack so its processes inherit the fresh values.
#
# Why this exists: hogli/phrocs spawn the temporal-worker (and friends) with the
# env that was present when the stack started. trycloudflare tunnels are
# ephemeral — when SANDBOX_API_URL / SANDBOX_LLM_GATEWAY_URL rotate in .env, a
# long-running worker keeps handing the *old* tunnel URL to Modal sandboxes, so
# the in-sandbox agent-server can't phone home ("fetch failed", gateway 404).
# Sourcing .env(.local) here and restarting fixes that without guesswork.
#
# Usage:
#   source scripts/load-posthog-code-env.sh
#   hogli start            # (or restart the temporal-worker) to pick up the env

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "This script must be sourced so env vars stay in your current shell."
    echo "Run: source scripts/load-posthog-code-env.sh"
    exit 1
fi

# Clear any stale values lingering in the shell so .env(.local) always wins,
# including vars that may have been removed from the files since last load.
unset \
    SANDBOX_PROVIDER SANDBOX_API_URL SANDBOX_LLM_GATEWAY_URL SANDBOX_MCP_URL \
    SANDBOX_MCP_TOKEN SANDBOX_JWT_PRIVATE_KEY \
    MODAL_TOKEN_ID MODAL_TOKEN_SECRET MODAL_IMAGE_BUILDER_VERSION \
    GITHUB_APP_CLIENT_ID GITHUB_APP_CLIENT_SECRET GITHUB_APP_PRIVATE_KEY GITHUB_APP_SLUG \
    SLACK_POSTHOG_CODE_CLIENT_ID SLACK_POSTHOG_CODE_CLIENT_SECRET SLACK_POSTHOG_CODE_SIGNING_SECRET

# Export everything from the env files. .env.local is sourced last so it wins,
# matching the usual local-override convention.
set -a
[ -f .env ] && source .env
[ -f .env.local ] && source .env.local
set +a

mask() { local v="${1}"; [ -z "$v" ] && echo "(unset)" || echo "set (len=${#v})"; }

echo "PostHog Code env loaded from .env + .env.local:"
echo
echo "  Sandbox / cloud-run routing (verify these match your live tunnels):"
echo "    SANDBOX_PROVIDER=${SANDBOX_PROVIDER:-(unset)}"
echo "    SANDBOX_API_URL=${SANDBOX_API_URL:-(unset)}"
echo "    SANDBOX_LLM_GATEWAY_URL=${SANDBOX_LLM_GATEWAY_URL:-(unset)}"
echo "    SANDBOX_MCP_URL=${SANDBOX_MCP_URL:-(unset)}"
echo "    SANDBOX_MCP_TOKEN=$(mask "${SANDBOX_MCP_TOKEN}")"
echo "    SANDBOX_JWT_PRIVATE_KEY=$(mask "${SANDBOX_JWT_PRIVATE_KEY}")"
echo
echo "  Modal:"
echo "    MODAL_TOKEN_ID=$(mask "${MODAL_TOKEN_ID}")"
echo "    MODAL_TOKEN_SECRET=$(mask "${MODAL_TOKEN_SECRET}")"
echo "    MODAL_IMAGE_BUILDER_VERSION=${MODAL_IMAGE_BUILDER_VERSION:-(unset)}"
echo
echo "  GitHub App:"
echo "    GITHUB_APP_SLUG=${GITHUB_APP_SLUG:-(unset)}"
echo "    GITHUB_APP_CLIENT_ID=$(mask "${GITHUB_APP_CLIENT_ID}")"
echo "    GITHUB_APP_CLIENT_SECRET=$(mask "${GITHUB_APP_CLIENT_SECRET}")"
echo "    GITHUB_APP_PRIVATE_KEY=$(mask "${GITHUB_APP_PRIVATE_KEY}")"
echo
echo "  Slack (PostHog Code app):"
echo "    SLACK_POSTHOG_CODE_CLIENT_ID=${SLACK_POSTHOG_CODE_CLIENT_ID:-(unset)}"
echo "    SLACK_POSTHOG_CODE_CLIENT_SECRET=$(mask "${SLACK_POSTHOG_CODE_CLIENT_SECRET}")"
echo "    SLACK_POSTHOG_CODE_SIGNING_SECRET=$(mask "${SLACK_POSTHOG_CODE_SIGNING_SECRET}")"
echo
echo "Next: restart so the temporal-worker picks up the fresh env:"
echo "  hogli start          # full stack, OR restart just the worker in your TUI"
echo
echo "Then trigger a cloud run, e.g.:"
echo "  python manage.py shell -c \"from posthog.models import Team; from products.tasks.backend.models import Task; \\"
echo "    Task.create_and_run(team=Team.objects.get(id=<team_id>), title='cloud e2e', \\"
echo "    description='Read the README and summarize it.', \\"
echo "    origin_product=Task.OriginProduct.SIGNAL_REPORT, user_id=<user_id>, \\"
echo "    repository='<org>/<repo>', mode='background', create_pr=False)\""
