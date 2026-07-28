"""Create a local-dev GitHub App via GitHub's App Manifest flow and write its
credentials to ``.env``.

This automates the manual walkthrough in ``docs/internal/sandboxes-setup-guide.md``
(and the ``_guide_github_app`` step of ``setup_background_agents``): instead of
clicking through the GitHub UI and copy-pasting four values, you run this command,
click "Create GitHub App" once in the browser, and the four ``GITHUB_APP_*`` vars
are written to ``.env`` for you.

The flow (see https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest):

1. We start a tiny localhost server and open a page that POSTs a pre-filled
   manifest to GitHub.
2. You click "Create GitHub App"; GitHub redirects back to the localhost server
   with a one-time ``code``.
3. We exchange the ``code`` at ``/app-manifests/{code}/conversions`` for the
   ``client_id``, ``client_secret``, ``slug`` and ``pem`` and persist them.

GitHub still requires that single human click — there is no fully headless way to
create an App — but everything else is automatic.
"""

import os
import re
import sys
import hmac
import html
import json
import time
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, quote, urlparse

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

import jwt
import requests

from posthog.egress.github.transport import github_request

GITHUB_APP_KEYS = ["GITHUB_APP_CLIENT_ID", "GITHUB_APP_CLIENT_SECRET", "GITHUB_APP_SLUG", "GITHUB_APP_PRIVATE_KEY"]
DEFAULT_BASE_URL = "http://localhost:8010"
DEFAULT_CALLBACK_PORT = 8019
DEFAULT_TIMEOUT_SECONDS = 600
# Permissions documented in docs/internal/sandboxes-setup-guide.md. Contents,
# pull requests and metadata are required; issues and workflows are documented as
# optional but cheap for a dev app and avoid "why doesn't X work" surprises.
DEFAULT_PERMISSIONS: dict[str, str] = {
    "contents": "write",
    "pull_requests": "write",
    "metadata": "read",
    "issues": "write",
    "workflows": "write",
}

_ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")

_FORM_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Create GitHub App</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
<h1>Creating your GitHub App…</h1>
<p>Submitting the manifest to GitHub. If you are not redirected automatically, click the button.</p>
<form action="__ACTION__" method="post">
<input type="hidden" name="manifest" value="__MANIFEST__">
<button type="submit" style="font-size:1rem;padding:0.5rem 1rem;">Continue to GitHub</button>
</form>
<script>document.forms[0].submit();</script>
</body></html>"""

_RESULT_PAGE_OK = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Done</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
<h1>GitHub App created 🎉</h1>
<p>Authorization received. Return to your terminal — the credentials are being written to
<code>.env</code>. You can close this tab.</p>
</body></html>"""

_RESULT_PAGE_ERROR = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Error</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto;">
<h1>Something went wrong</h1><p>__ERROR__</p><p>Check your terminal for details.</p>
</body></html>"""


class _ManifestCallbackHandler(BaseHTTPRequestHandler):
    """Serves the auto-submitting manifest form and receives GitHub's redirect."""

    def log_message(self, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        server = cast(_ManifestCallbackServer, self.server)
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._serve_form(server)
        elif parsed.path == "/callback":
            self._handle_callback(server, parse_qs(parsed.query))
        else:
            self.send_error(404)

    def _serve_form(self, server: "_ManifestCallbackServer") -> None:
        page = _FORM_PAGE.replace("__ACTION__", html.escape(server.action_url, quote=True)).replace(
            "__MANIFEST__", html.escape(server.manifest_json, quote=True)
        )
        self._write_html(200, page)

    def _handle_callback(self, server: "_ManifestCallbackServer", query: dict[str, list[str]]) -> None:
        state = (query.get("state") or [""])[0]

        if not hmac.compare_digest(state, server.expected_state):
            self._write_html(400, _RESULT_PAGE_ERROR.replace("__ERROR__", "Unexpected request — ignored."))
            return

        code = (query.get("code") or [""])[0]
        if code:
            result: dict[str, str] = {"code": code}
            self._write_html(200, _RESULT_PAGE_OK)
        else:
            error = (query.get("error_description") or query.get("error") or ["GitHub returned no code"])[0]
            result = {"error": error}
            self._write_html(400, _RESULT_PAGE_ERROR.replace("__ERROR__", html.escape(error)))

        server.result = result
        server.done.set()

    def _write_html(self, status: int, body_html: str) -> None:
        body = body_html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ManifestCallbackServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, port: int, *, action_url: str, manifest_json: str, expected_state: str) -> None:
        super().__init__(("127.0.0.1", port), _ManifestCallbackHandler)
        self.action_url = action_url
        self.manifest_json = manifest_json
        self.expected_state = expected_state
        self.done = threading.Event()
        self.result: dict[str, str] | None = None


class Command(BaseCommand):
    help = "Create a local-dev GitHub App via the manifest flow and write GITHUB_APP_* to .env."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--org",
            type=str,
            default=None,
            help="Create the app under this GitHub organization instead of your personal account.",
        )
        parser.add_argument(
            "--name",
            type=str,
            default=None,
            help="App name (must be globally unique on GitHub). Defaults to 'PostHog Signals Dev <random>'.",
        )
        parser.add_argument(
            "--base-url",
            type=str,
            default=DEFAULT_BASE_URL,
            help=f"PostHog base URL for the homepage/callback/setup URLs (default {DEFAULT_BASE_URL}).",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=DEFAULT_CALLBACK_PORT,
            help=f"Local port for the manifest callback server (default {DEFAULT_CALLBACK_PORT}).",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=DEFAULT_TIMEOUT_SECONDS,
            help=f"Seconds to wait for you to finish in the browser (default {DEFAULT_TIMEOUT_SECONDS}).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Overwrite existing GITHUB_APP_* values in .env without prompting.",
        )
        parser.add_argument(
            "--no-browser",
            action="store_true",
            help="Don't auto-open the browser; just print the URL to visit.",
        )
        parser.add_argument(
            "--no-verify",
            action="store_true",
            help="Skip the post-creation auth check that confirms the private key works.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        if not settings.DEBUG:
            raise CommandError("This command creates a local-dev GitHub App and can only run with DEBUG=1.")

        org: str | None = options["org"]
        name: str = options["name"] or f"PostHog Signals Dev {secrets.token_hex(3)}"
        base_url: str = options["base_url"]
        port: int = options["port"]
        timeout: int = options["timeout"]
        verify: bool = not options["no_verify"]

        env_path = Path(settings.BASE_DIR) / ".env"
        self._confirm_overwrite(env_path, options["force"])

        state = secrets.token_urlsafe(24)
        manifest = _build_manifest(name=name, base_url=base_url, redirect_url=f"http://127.0.0.1:{port}/callback")
        server = self._start_server(
            port,
            action_url=_manifest_action_url(org, state),
            manifest_json=json.dumps(manifest),
            expected_state=state,
        )

        owner = f"organization '{org}'" if org else "your personal account (whichever you're signed into)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Creating GitHub App '{name}'"))
        self.stdout.write(f"  Owner: {owner}")
        try:
            data = self._run_browser_flow(server, port, open_browser=not options["no_browser"], timeout=timeout)
        finally:
            server.shutdown()
            server.server_close()

        self._save_and_report(data, env_path=env_path, base_url=base_url, verify=verify)

    def _confirm_overwrite(self, env_path: Path, force: bool) -> None:
        existing = _existing_github_keys(env_path)
        if not existing or force:
            return
        message = f"Already set ({', '.join(existing)}) in {env_path} or your environment."
        if not sys.stdin.isatty():
            raise CommandError(f"{message} Re-run with --force to overwrite.")
        answer = input(f"  {message}\n  Overwrite with the new app's credentials? [y/N]: ").strip().lower()
        if answer != "y":
            raise CommandError("Aborted — no app created.")

    def _start_server(
        self, port: int, *, action_url: str, manifest_json: str, expected_state: str
    ) -> _ManifestCallbackServer:
        try:
            server = _ManifestCallbackServer(
                port, action_url=action_url, manifest_json=manifest_json, expected_state=expected_state
            )
        except OSError as err:
            raise CommandError(f"Could not bind to 127.0.0.1:{port} ({err}). Pass --port to pick another.") from err
        threading.Thread(target=server.serve_forever, name="github-app-manifest", daemon=True).start()
        return server

    def _run_browser_flow(
        self,
        server: _ManifestCallbackServer,
        port: int,
        *,
        open_browser: bool,
        timeout: int,
    ) -> dict[str, Any]:
        start_url = f"http://127.0.0.1:{port}/"
        opened = False
        if open_browser:
            try:
                opened = webbrowser.open(start_url)
            except Exception:
                opened = False
        if opened:
            self.stdout.write(f"  Opened {start_url} — click 'Create GitHub App' in your browser.")
        else:
            self.stdout.write(f"  Open this URL and click 'Create GitHub App':\n    {start_url}")

        if not server.done.wait(timeout):
            raise CommandError(f"Timed out after {timeout}s waiting for GitHub. Re-run when ready.")
        result = server.result or {"error": "no result received"}
        if "error" in result:
            raise CommandError(f"GitHub App creation failed: {result['error']}")
        return self._exchange_code(result["code"])

    def _exchange_code(self, code: str) -> dict[str, Any]:
        self.stdout.write("  Exchanging authorization code for credentials…")
        try:
            resp = github_request(
                "POST",
                f"https://api.github.com/app-manifests/{quote(code, safe='')}/conversions",
                source="signals",
                timeout=30,
            )
        except requests.RequestException as err:
            raise CommandError(f"Network error contacting GitHub: {err}") from err
        if resp.status_code not in (200, 201):
            raise CommandError(f"GitHub manifest conversion failed ({resp.status_code}): {resp.text[:500]}")
        data: dict[str, Any] = resp.json()
        missing = [field for field in ("client_id", "client_secret", "slug", "pem") if not data.get(field)]
        if missing:
            raise CommandError(f"GitHub response was missing expected fields: {', '.join(missing)}.")
        return data

    def _save_and_report(self, data: dict[str, Any], *, env_path: Path, base_url: str, verify: bool) -> None:
        pem: str = data["pem"]
        _upsert_env_vars(
            env_path,
            {
                "GITHUB_APP_CLIENT_ID": data["client_id"],
                "GITHUB_APP_CLIENT_SECRET": data["client_secret"],
                "GITHUB_APP_SLUG": data["slug"],
                "GITHUB_APP_PRIVATE_KEY": _format_private_key_for_env(pem),
            },
        )
        self.stdout.write(self.style.SUCCESS(f"  Wrote {', '.join(GITHUB_APP_KEYS)} to {env_path}"))

        if verify:
            self._verify_key(data["client_id"], pem)

        slug = data["slug"]
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("GitHub App created."))
        self.stdout.write(f"  Name:     {data.get('name', slug)}")
        self.stdout.write(f"  Slug:     {slug}")
        if data.get("id"):
            self.stdout.write(f"  App ID:   {data['id']}")
        if data.get("html_url"):
            self.stdout.write(f"  Settings: {data['html_url']}")
        self.stdout.write("")
        self.stdout.write("Next steps:")
        self.stdout.write(f"  1. Install it on your test repos: https://github.com/apps/{slug}/installations/new")
        self.stdout.write(f"     (or via PostHog: {base_url.rstrip('/')}/project/1/integrations/github)")
        self.stdout.write("  2. Restart your dev server so it picks up the new .env values.")

    def _verify_key(self, client_id: str, pem: str) -> None:
        env_formatted = _format_private_key_for_env(pem)
        loaded_key = env_formatted.replace("\\n", "\n").strip()
        now = int(time.time())
        try:
            token = jwt.encode(
                {"iat": now - 60, "exp": now + 300, "iss": client_id},
                loaded_key,
                algorithm="RS256",
            )
            resp = github_request(
                "GET",
                "https://api.github.com/app",
                source="signals",
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
        except Exception as err:
            self.stdout.write(
                self.style.WARNING(f"  Could not verify the key against GitHub ({err}); it was still saved.")
            )
            return
        if resp.status_code == 200:
            self.stdout.write(
                self.style.SUCCESS(f"  Verified: authenticated to GitHub as '{resp.json().get('name', client_id)}'.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"  Key verification returned {resp.status_code}; it was still saved.")
            )


def _build_manifest(*, name: str, base_url: str, redirect_url: str) -> dict[str, Any]:
    """Build the GitHub App manifest matching the documented local-dev config.

    ``redirect_url`` is where GitHub sends the one-time creation ``code`` (our local
    server) — distinct from ``callback_urls``, which are the App's own OAuth callbacks.
    ``hook_attributes`` is omitted so the webhook is created inactive with no URL.
    """
    base = base_url.rstrip("/")
    return {
        "name": name,
        "url": f"{base}/",
        "description": "PostHog local dev GitHub App (Signals / background agents).",
        "public": False,
        "redirect_url": redirect_url,
        "callback_urls": [
            f"{base}/integrations/github/callback",
            f"{base}/complete/github-link/",
        ],
        "setup_url": f"{base}/integrations/github/callback",
        "request_oauth_on_install": True,
        "setup_on_update": False,
        "default_events": [],
        "default_permissions": dict(DEFAULT_PERMISSIONS),
    }


def _manifest_action_url(org: str | None, state: str) -> str:
    base = (
        f"https://github.com/organizations/{org}/settings/apps/new" if org else "https://github.com/settings/apps/new"
    )
    return f"{base}?state={quote(state, safe='')}"


def _format_private_key_for_env(pem: str) -> str:
    """Encode the PEM as a single line with literal ``\\n``, as the App reader expects."""
    return pem.strip().replace("\n", "\\n")


def _existing_github_keys(env_path: Path) -> list[str]:
    keys_in_file: set[str] = set()
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            match = _ENV_KEY_RE.match(line)
            if match:
                keys_in_file.add(match.group("key"))
    return [key for key in GITHUB_APP_KEYS if os.environ.get(key) or key in keys_in_file]


def _upsert_env_vars(env_path: Path, values: dict[str, str]) -> None:
    """Replace existing ``KEY=`` lines in place; append any that are missing. Values are quoted."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    remaining = dict(values)
    out: list[str] = []
    for line in lines:
        match = _ENV_KEY_RE.match(line)
        key = match.group("key") if match else None
        if key in remaining:
            out.append(f'{key}="{remaining.pop(key)}"')
        else:
            out.append(line)
    if remaining:
        if out and out[-1].strip():
            out.append("")
        out.append("# GitHub App credentials (written by create_github_app)")
        out.extend(f'{key}="{value}"' for key, value in remaining.items())
    env_path.write_text("\n".join(out) + "\n")
