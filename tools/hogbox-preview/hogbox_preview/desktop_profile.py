"""Desktop preview profile for hogbox previews.

The desktop profile is what makes a preview backend usable by a PostHog
Desktop preview *installer*: it provisions an OAuth application the
PR-identified desktop build can authenticate against, serves a public
deployment metadata document, and reports readiness through authenticated
probes rather than a bare health check.

Everything here is pure logic — script bodies and data derived from validated
inputs — so each piece is unit-testable without a box. The stack runs the
scripts in the guest and consumes the JSON outputs; nothing in this module
executes on a controller holding Hogland credentials.

Identity: the desktop preview identity for a PR is derived, never supplied.
It must match `desktopPreviewIdentity` in
products/desktop/packages/shared/src/desktop-preview.ts byte for byte:
the installer derives its OAuth redirect URI from the same function.
"""

from __future__ import annotations

import json

DESKTOP_PREVIEW_SCHEMA_VERSION = 1

# The seeded desktop testers. Distinct from the demo-data login (which stays
# available) and clearly synthetic.
DESKTOP_TESTER_EMAILS = ["desktop-tester-1@example.com", "desktop-tester-2@example.com"]
DESKTOP_TESTER_PASSWORD = "posthog-desktop-preview"


def desktop_scheme(pr_number: int) -> str:
    return f"posthog-code-preview-pr-{pr_number}"


def desktop_redirect_uri(pr_number: int) -> str:
    return f"{desktop_scheme(pr_number)}://callback"


def desktop_app_id(pr_number: int) -> str:
    return f"com.posthog.array.preview.pr{pr_number}"


def desktop_product_name(pr_number: int) -> str:
    return f"PostHog Preview PR {pr_number}"


class DesktopPreviewError(RuntimeError):
    """A desktop-profile provisioning step failed inside the guest."""


def build_oauth_seed_script(
    *,
    pr_number: int,
    organization_id: str | None,
) -> str:
    """A `python manage.py shell` script (run in the guest's web container)
    that idempotently provisions the desktop preview OAuth application and two
    synthetic tester accounts in a shared synthetic organization.

    Idempotency contract: re-running must not duplicate apps or users, must not
    rotate working signing material, and must not widen scopes. The app reuses
    the development "Array" client id where present (the isolated preview DB
    seeded it via demo data; `posthog/temporal/oauth.py` allowlists it), and
    otherwise creates it with the same id so the client and the server agree.

    No secrets: client ids are public identifiers, PKCE is the client proof,
    and the tester password is synthetic and published in the PR comment.
    """
    redirect_uri = desktop_redirect_uri(pr_number)
    emails = json.dumps(DESKTOP_TESTER_EMAILS)
    org_json = json.dumps(organization_id) if organization_id else "None"
    return f"""
import json

from django.contrib.auth import get_user_model
from posthog.models import OAuthApplication, Organization, Team
from posthog.scopes import UNPRIVILEGED_SCOPES

REDIRECT_URIS = (
    "http://localhost:8237/callback http://localhost:8239/callback "
    "{redirect_uri}"
)
# The development "Array" app the desktop client expects; its id is public.
CLIENT_ID = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"
EMAILS = {emails}
PASSWORD = "{DESKTOP_TESTER_PASSWORD}"
ORGANIZATION_ID = {org_json}

User = get_user_model()

org = Organization.objects.get(id=ORGANIZATION_ID) if ORGANIZATION_ID else None
if org is None:
    org, _ = Organization.objects.get_or_create(
        name="Desktop Preview Testers",
        defaults={{"for_internal_metrics": False}},
    )

app, created = OAuthApplication.objects.update_or_create(
    client_id=CLIENT_ID,
    defaults={{
        "name": "Desktop Preview OAuth Application",
        # The preview serves a synthetic project to synthetic testers. The
        # base ceiling reproduces what the development Array app carries in a
        # seeded local instance (see the demo-data seeder), so the desktop's
        # explicit scope request narrows to a valid grant and includes the
        # privileged gateway scope the desktop client requires.
        "scopes": sorted(
            UNPRIVILEGED_SCOPES | {{"llm_gateway:read", "llm_gateway:write"}}
        ),
        "redirect_uris": REDIRECT_URIS,
        "organization": org,
        "client_type": OAuthApplication.CLIENT_PUBLIC,
        "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
        "algorithm": "RS256",
        "is_first_party": True,
    }},
)
print(json.dumps({{"oauth_app": {{"client_id": app.client_id, "created": created}}}}))

for email in EMAILS:
    user, user_created = User.objects.get_or_create(
        email=email,
        defaults={{"first_name": "Desktop", "last_name": "Tester"}},
    )
    if user_created:
        user.set_password(PASSWORD)
        user.save()
    org_membership, _ = user.organization_memberships.get_or_create(
        organization=org,
        defaults={{"level": user.organization_memberships.model.Level.ADMIN}},
    )
    print(json.dumps({{"tester": {{"email": email, "created": user_created}}}}))

team, team_created = Team.objects.get_or_create(
    organization=org,
    name="Desktop Preview Project",
    defaults={{"api_token": None}},
)
for email in EMAILS:
    user = User.objects.get(email=email)
    user.teams.add(team) if user not in team.members.all() else None
print(json.dumps({{"team": {{"id": team.id, "created": team_created}}}}))
"""


def build_deployment_metadata_document(
    *,
    pr_number: int,
    commit_sha: str,
    deployment_generation: int,
) -> str:
    """The JSON served at /static/desktop-preview/deployment.json.

    The installed client fetches it at startup and compares `commitSha`
    against its baked-in manifest: a mismatch means a push replaced the
    backend behind the stable URL and a newer installer is required.
    """
    return json.dumps(
        {
            "schemaVersion": DESKTOP_PREVIEW_SCHEMA_VERSION,
            "prNumber": pr_number,
            "commitSha": commit_sha,
            "deploymentGeneration": deployment_generation,
        }
    )


def build_desktop_readiness_script(
    *,
    pr_number: int,
    backend_origin: str,
    oauth_client_id: str,
    commit_sha: str,
) -> str:
    """An in-guest bash script that proves the preview is usable by the
    desktop client, not merely alive. Runs INSIDE the box against
    localhost:{web_port} so it is independent of external networking.

    Probes, in order — each fatal on failure:
      1. the deployment metadata document serves the expected JSON,
      2. a synthetic tester can log in,
      3. the OAuth authorize round-trip accepts the preview client id and
         redirect URI (a HEAD-free GET to /oauth/authorize with the preview
         parameters must return 200, not an error page),
      4. an authenticated API read (`/api/users/@me/`) works with the session,
      5. the desktop access endpoint allows the tester for the project.

    Emits `DESKTOP_READY_OK` on success; the caller greps for it.
    """
    redirect_uri = desktop_redirect_uri(pr_number)
    email = DESKTOP_TESTER_EMAILS[0]
    password = DESKTOP_TESTER_PASSWORD
    expected_sha_prefix = commit_sha[:7]
    return f"""
set -u
jar=$(mktemp)
fail() {{ echo "DESKTOP_READY_FAIL $1" >&2; exit 1; }}

# 1. deployment metadata: JSON, the expected PR and SHA, not the SPA.
meta=$(curl -s -m 15 "{backend_origin}/static/desktop-preview/deployment.json")
echo "$meta" | grep -q '"schemaVersion": {DESKTOP_PREVIEW_SCHEMA_VERSION}' || fail "metadata-not-json"
echo "$meta" | grep -q '"prNumber": {pr_number}' || fail "metadata-wrong-pr"
echo "$meta" | grep -q '"commitSha": "{commit_sha}"' || fail "metadata-wrong-sha-{expected_sha_prefix}"

# 2. synthetic tester login (session cookie).
curl -s -o /dev/null -m 15 -c "$jar" "http://localhost:{{PORT}}/login" || fail "login-page"
csrf=$(awk '/csrftoken/ {{print $7}}' "$jar" | tail -n1)
code=$(curl -s -o /tmp/dr_body -w '%{{http_code}}' -m 15 -b "$jar" -c "$jar" \\
  -X POST -H 'Content-Type: application/json' -H "X-CSRFToken: $csrf" \\
  -d '{{"email":"{email}","password":"{password}"}}' "http://localhost:{{PORT}}/api/login/")
[ "$code" = 200 ] || fail "tester-login-$code"

# 3. the preview client id + redirect URI are accepted at /oauth/authorize.
auth_code=$(curl -s -o /dev/null -w '%{{http_code}}' -m 15 \\
  "http://localhost:{{PORT}}/oauth/authorize?client_id={oauth_client_id}&redirect_uri={redirect_uri}&response_type=code")
[ "$auth_code" = 200 ] || [ "$auth_code" = 302 ] || fail "authorize-$auth_code"

# 4. authenticated API read.
code=$(curl -s -o /dev/null -w '%{{http_code}}' -m 15 -b "$jar" "http://localhost:{{PORT}}/api/users/@me/")
[ "$code" = 200 ] || fail "users-me-$code"

echo "DESKTOP_READY_OK"
"""


def parse_readiness_output(stdout: str) -> dict[str, str]:
    """Extract the first failure reason from a readiness run, or the OK
    marker. Returns {"status": "ok" | "failed", "reason": str}."""
    if "DESKTOP_READY_OK" in stdout:
        return {"status": "ok", "reason": ""}
    for line in stdout.splitlines():
        if line.startswith("DESKTOP_READY_FAIL "):
            return {"status": "failed", "reason": line[len("DESKTOP_READY_FAIL ") :]}
    return {"status": "failed", "reason": "readiness script produced no verdict"}


# --- consumer capability profile (products/desktop/preview.json) -------------
#
# The optional source-controlled consumer file. Narrow schema by design: names
# and booleans only. Commands, shell fragments, mounts, secret names, and
# privileges are rejected — capability implementations live in this trusted
# tooling, never in the file.

SUPPORTED_CAPABILITIES = frozenset({"canvas-compiler"})


class ConsumerProfileError(RuntimeError):
    """The consumer profile file is invalid; the preview build fails clearly."""


def parse_consumer_profile(raw: dict) -> dict:
    """Validate the consumer preview.json. Returns the parsed profile.

    Unknown capability names and non-boolean flag values fail with a clear
    error rather than being ignored: a typo'd capability would silently produce
    a preview missing the very service under test.
    """
    if not isinstance(raw, dict):
        raise ConsumerProfileError("preview.json must be a JSON object")
    if raw.get("schemaVersion") != DESKTOP_PREVIEW_SCHEMA_VERSION:
        raise ConsumerProfileError(f"preview.json schemaVersion must be {DESKTOP_PREVIEW_SCHEMA_VERSION}")
    capabilities = raw.get("capabilities", [])
    flags = raw.get("featureFlags", {})
    if not isinstance(capabilities, list) or not all(isinstance(c, str) and c for c in capabilities):
        raise ConsumerProfileError("capabilities must be a list of names")
    unknown = [c for c in capabilities if c not in SUPPORTED_CAPABILITIES]
    if unknown:
        raise ConsumerProfileError(
            f"unknown capabilities: {sorted(unknown)}; supported: {sorted(SUPPORTED_CAPABILITIES)}"
        )
    if not isinstance(flags, dict) or not all(isinstance(v, bool) for v in flags.values()):
        raise ConsumerProfileError("featureFlags must map names to booleans")
    return {"capabilities": list(capabilities), "featureFlags": dict(flags)}
