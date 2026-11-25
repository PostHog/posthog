#!/bin/sh
# Register Meep's OAuth application with a local PostHog (http://localhost:8010)
# and save its public client ID where the app looks for it.
#
#   MEEP_DEV_DIR=/abs/dir sh scripts/posthog-local-app.sh [--verify /path/to/posthog]
#
# Registration uses PostHog's dynamic client registration, with the redirect URI
# and scopes the app asks for. --verify also marks the application verified in
# that PostHog checkout's database, so the consent screen drops its
# "Unverified application" warning. Run it again to replace the registration,
# for example after the app requests new scopes.
set -eu
cd "$(dirname "$0")/.."

origin=http://localhost:8010
posthog=
if [ "${1:-}" = "--verify" ]; then
    posthog=${2:?--verify needs the PostHog checkout directory}
fi
case "${MEEP_DEV_DIR:-}" in
    /*) ;;
    *) printf '%s\n' 'Set MEEP_DEV_DIR to the absolute directory used with scripts/dev.sh --local.' >&2; exit 2 ;;
esac
mkdir -p "$MEEP_DEV_DIR"

# The scopes come from the app itself so the registration never drifts from it.
scopes=$(sed -n '/^const SCOPES: &\[&str\] = &\[/,/^\];/p' apps/meep/src/backend.rs \
    | grep -o '"[a-z_]*:[a-z]*"' | tr -d '"' | tr '\n' ' ')
[ -n "$scopes" ] || { printf '%s\n' 'Could not read SCOPES from apps/meep/src/backend.rs.' >&2; exit 1; }

client_id=$(ORIGIN="$origin" SCOPES="$scopes" python3 - <<'PY'
import json, os, sys, urllib.request

origin = os.environ["ORIGIN"]
def call(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)
try:
    discovery = call(origin + "/.well-known/oauth-authorization-server")
    app = call(discovery["registration_endpoint"], {
        "client_name": "Meep local",
        "redirect_uris": ["http://127.0.0.1:43180/callback"],
        "response_types": ["code"],
        "grant_types": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_method": "none",
        "scope": os.environ["SCOPES"].strip(),
    })
except Exception as error:
    sys.exit(f"Registration with {origin} failed: {error}")
print(app["client_id"])
PY
)
umask 077
printf '%s\n' "$client_id" > "$MEEP_DEV_DIR/posthog-local-client-id"
printf '%s\n' "Registered \"Meep local\"; client ID saved to $MEEP_DEV_DIR/posthog-local-client-id"

if [ -n "$posthog" ]; then
    python=python3
    [ -x "$posthog/.flox/cache/venv/bin/python" ] && python="$posthog/.flox/cache/venv/bin/python"
    # A single-field update: a full save would also validate signing settings
    # that only the running server has.
    (cd "$posthog" && MEEP_CLIENT_ID="$client_id" DEBUG=1 "$python" manage.py shell -c '
import os
from posthog.models.oauth import OAuthApplication
updated = OAuthApplication.objects.filter(client_id=os.environ["MEEP_CLIENT_ID"]).update(is_verified=True)
print("Marked verified" if updated else "Application not found")
' 2>/dev/null | grep -E "^(Marked verified|Application not found)$") ||
        { printf '%s\n' "Could not mark it verified through $posthog/manage.py." >&2; exit 1; }
fi
printf '%s\n' 'Sign in again with Local in Meep to use it.'
