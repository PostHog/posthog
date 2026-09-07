"""Guest scripts for the desktop preview OAuth and deployment contracts."""

from __future__ import annotations

DESKTOP_OAUTH_CLIENT_ID = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"
DESKTOP_TESTER_EMAILS = ["desktop-tester-1@example.com", "desktop-tester-2@example.com"]
DESKTOP_TESTER_PASSWORD = "posthog-desktop-preview"
LLM_GATEWAY_IMAGE = "ghcr.io/posthog/posthog/llm-gateway:master"
LLM_GATEWAY_PATH_PREFIX = "/llm-gateway"
PROXY_IMAGE = "caddy:2.10-alpine"
DESKTOP_PREVIEW_IMAGES = [PROXY_IMAGE, LLM_GATEWAY_IMAGE]
# hogpanion's bedrock feature serves renewable AWS credentials here inside every box.
BEDROCK_CREDENTIALS_URL = "http://127.0.0.1:8181/credentials"
BEDROCK_REGION = "us-east-1"


class DesktopPreviewError(RuntimeError):
    pass


def desktop_redirect_uri(pr_number: int) -> str:
    # Keep the OS callback identical to desktopPreviewIdentity in @posthog/shared.
    return f"posthog-code-preview-pr-{pr_number}://callback"


def build_oauth_seed_script(*, pr_number: int) -> str:
    # Execute through manage.py shell so Django initializes before model imports.
    # The application id is pinned to the gateway's POSTHOG_CODE_DEV_APP_ID: the
    # gateway authorizes posthog_code tokens by the application's database UUID,
    # so a random id would fail every agent request with "not authorized".
    # Keep in sync with posthog/temporal/oauth.py and llm_gateway/products/config.py.
    return f"""
import secrets
from uuid import UUID

from django.db import transaction
from posthog.models import OAuthApplication, Organization, OrganizationMembership, Team, User

DESKTOP_PREVIEW_APP_ID = UUID("019ebb47-c750-0000-e1ea-723a6ff112d3")

with transaction.atomic():
    org, _ = Organization.objects.get_or_create(name="Desktop Preview Testers")
    team = Team.objects.filter(organization=org, name="Desktop Preview Project").first()
    if team is None:
        # TeamManager.create also creates the required Project; QuerySet.get_or_create does not.
        team = Team.objects.create(organization=org, name="Desktop Preview Project")
    clash = OAuthApplication.objects.filter(client_id={DESKTOP_OAUTH_CLIENT_ID!r}, id=DESKTOP_PREVIEW_APP_ID).first() is None and OAuthApplication.objects.filter(id=DESKTOP_PREVIEW_APP_ID).exists()
    if clash:
        raise RuntimeError("OAuth application id DESKTOP_PREVIEW_APP_ID is taken by another application; the gateway allowlist expects it on this client_id")
    OAuthApplication.objects.update_or_create(
        client_id={DESKTOP_OAUTH_CLIENT_ID!r},
        defaults={{
            "id": DESKTOP_PREVIEW_APP_ID,
            "name": "Desktop Preview",
            "scopes": ["@default", "llm_gateway:read"],
            "optional_scopes": [],
            "redirect_uris": {desktop_redirect_uri(pr_number)!r},
            "organization": org,
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "algorithm": "RS256",
            "is_first_party": True,
        }},
    )
    for email in {DESKTOP_TESTER_EMAILS!r}:
        user, created = User.objects.get_or_create(email=email, defaults={{"first_name": "Desktop Tester"}})
        if created:
            user.set_password({DESKTOP_TESTER_PASSWORD!r})
        if not user.distinct_id:
            user.distinct_id = secrets.token_urlsafe(32)
        user.save()
        OrganizationMembership.objects.get_or_create(
            user=user, organization=org, defaults={{"level": OrganizationMembership.Level.ADMIN}},
        )
        user.current_organization = org
        user.current_team = team
        user.save(update_fields=["current_organization", "current_team"])
print("DESKTOP_SEED_OK")
"""


def build_desktop_readiness_script(*, pr_number: int, web_port: int) -> str:
    # Probe inside the guest to avoid depending on its ability to reach the VPN edge.
    return f"""
import base64
import hashlib
import http.cookiejar
import json
import secrets
import urllib.parse
import urllib.request

base = "http://localhost:{web_port}"
# The guest probes loopback over HTTP; the browser-facing server keeps Secure cookies.
jar = http.cookiejar.CookieJar(policy=http.cookiejar.DefaultCookiePolicy(secure_protocols=("http", "https")))
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

def request(path, data=None, token=None, form=False):
    headers = {{"Referer": base + "/"}}
    if data is not None:
        headers["X-CSRFToken"] = next((cookie.value for cookie in jar if cookie.name == "csrftoken"), "")
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
        data = (urllib.parse.urlencode(data) if form else json.dumps(data)).encode()
    if token:
        headers["Authorization"] = "Bearer " + token
    with opener.open(urllib.request.Request(base + path, data=data, headers=headers), timeout=15) as response:
        if response.status != 200:
            raise RuntimeError(f"{{path}} returned HTTP {{response.status}}")
        return response.read()

def read_json(path, **kwargs):
    return json.loads(request(path, **kwargs))

request("/login")
read_json("/api/login/", data={{"email": {DESKTOP_TESTER_EMAILS[0]!r}, "password": {DESKTOP_TESTER_PASSWORD!r}}})
project = read_json("/api/projects/@current/")
verifier = secrets.token_urlsafe(48)
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
redirect_uri = {desktop_redirect_uri(pr_number)!r}
authorization = read_json("/oauth/authorize/", data={{
    "client_id": {DESKTOP_OAUTH_CLIENT_ID!r}, "redirect_uri": redirect_uri,
    "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
    "scope": "openid profile email project:read user:read llm_gateway:read",
    "allow": True, "access_level": "team", "scoped_teams": [project["id"]],
}})
redirect = urllib.parse.urlsplit(authorization["redirect_to"])
if redirect.scheme + "://" + redirect.netloc != redirect_uri:
    raise RuntimeError("OAuth returned an unexpected redirect")
params = urllib.parse.parse_qs(redirect.query)
if "code" not in params or "error" in params:
    raise RuntimeError("OAuth authorization failed: " + params.get("error", ["missing code"])[0])
tokens = read_json("/oauth/token/", form=True, data={{
    "grant_type": "authorization_code", "client_id": {DESKTOP_OAUTH_CLIENT_ID!r},
    "redirect_uri": redirect_uri, "code": params["code"][0], "code_verifier": verifier,
}})
# Remove browser cookies so these probes prove the issued OAuth token works.
jar.clear()
token = tokens["access_token"]
read_json("/api/users/@me/", token=token)
access = read_json(f"/api/projects/{{project['id']}}/desktop/access/", token=token)
if access.get("allowed") is not True:
    raise RuntimeError("Desktop access denied: " + str(access.get("reason")))
print("DESKTOP_READY_TOKEN=" + token)
print("DESKTOP_READY_PROJECT=" + str(project["id"]))
print("DESKTOP_READY_OK")
"""


def build_gateway_compose_lines(*, web_port: int) -> list[str]:
    # The box exposes one HTTP port. A proxy takes it over from web and routes the
    # gateway under a path prefix, so the installer needs no second hostname.
    # Both containers use the host network: hogpanion serves renewable Bedrock
    # credentials on the guest loopback only, and the proxy reaches web through
    # its published host port.
    web_host_port = web_port + 1
    caddyfile = [
        f":{web_port} {{",
        f"  handle_path {LLM_GATEWAY_PATH_PREFIX}/* {{",
        "    reverse_proxy 127.0.0.1:8080 {",
        "      header_up x-posthog-provider bedrock",
        "      flush_interval -1",
        "    }",
        "  }",
        "  handle {",
        f"    reverse_proxy 127.0.0.1:{web_host_port}",
        "  }",
        "}",
    ]
    # Returns the gateway lines only. write_override() already opens the `web:`
    # key, and Compose rejects a duplicate mapping key, so the caller folds the
    # port override into its own web block.
    return [
        "    ports: !override",
        f"      - {web_host_port}:8000",
        "  desktop-preview-proxy:",
        f"    image: {PROXY_IMAGE}",
        "    restart: always",
        "    network_mode: host",
        "    entrypoint: sh",
        '    command: -c \'printf "%s" "$$CADDYFILE" > /etc/caddy/Caddyfile && exec caddy run -c /etc/caddy/Caddyfile\'',
        "    environment:",
        "      CADDYFILE: |",
        *[f"        {line}" for line in caddyfile],
        "  llm-gateway:",
        f"    image: {LLM_GATEWAY_IMAGE}",
        "    restart: always",
        "    network_mode: host",
        "    environment:",
        # The gateway's pydantic settings read only the LLM_GATEWAY_ prefix;
        # unprefixed names fall back to production defaults.
        "      - LLM_GATEWAY_DATABASE_URL=postgres://posthog:posthog@localhost:5432/posthog",
        f"      - LLM_GATEWAY_POSTHOG_API_BASE_URL=http://localhost:{web_host_port}",
        f"      - LLM_GATEWAY_BEDROCK_REGION_NAME={BEDROCK_REGION}",
        f"      - AWS_REGION={BEDROCK_REGION}",
        f"      - AWS_CONTAINER_CREDENTIALS_FULL_URI={BEDROCK_CREDENTIALS_URL}",
        "      - LLM_GATEWAY_METRICS_ENABLED=false",
    ]
