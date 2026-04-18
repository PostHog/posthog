import os
import re
import sys
import subprocess
import webbrowser
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import OAuthApplication, Team
from posthog.models.feature_flag import FeatureFlag
from posthog.temporal.oauth import ARRAY_APP_CLIENT_ID_DEV

AUTO_FILL_KEYS = ["OIDC_RSA_PRIVATE_KEY", "SANDBOX_JWT_PRIVATE_KEY", "DEBUG", "SANDBOX_PROVIDER"]
GITHUB_APP_KEYS = ["GITHUB_APP_CLIENT_ID", "GITHUB_APP_SLUG", "GITHUB_APP_PRIVATE_KEY"]
# Canonical local-dev redirect URIs for the Array OAuth app (matches
# posthog/demo/products/hedgebox/matrix.py and docs/published/handbook/engineering/oauth-development-guide.md).
EXPECTED_REDIRECT_URIS = (
    "http://localhost:3000/callback "
    "https://example.com/callback "
    "http://localhost:8237/callback "
    "http://localhost:8239/callback"
)
GITHUB_APP_NEW_URL = "https://github.com/settings/apps/new"
GITHUB_APP_SETUP_URL = "http://localhost:8010/integrations/github/callback"


class Command(BaseCommand):
    help = "Set up everything needed to run background agents locally. Idempotent — safe to run multiple times."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only be run with DEBUG=1")

        repo_root = Path(settings.BASE_DIR)
        env_path = repo_root / ".env"
        env_example_path = repo_root / ".env.example"

        self._check_database()
        env_file_values = self._ensure_env_vars(env_path, env_example_path)
        self._setup_oauth_app()
        self._setup_feature_flags()
        self._build_skills()
        self._guide_github_app(env_file_values)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Background agents setup complete!"))
        self.stdout.write("Run `hogli start` to launch the dev environment.")

    def _check_database(self):
        from django.db import connection

        try:
            connection.ensure_connection()
        except Exception as e:
            raise CommandError(f"Cannot connect to the database. Is the dev environment running? (hogli start)\n{e}")

    def _ensure_env_vars(self, env_path: Path, env_example_path: Path) -> dict[str, str]:
        """Append missing AUTO_FILL_KEYS to .env. Returns the post-write contents of .env."""
        self.stdout.write(self.style.MIGRATE_HEADING("Ensuring environment variables..."))

        if not env_example_path.exists():
            self.stdout.write(self.style.ERROR(f"  {env_example_path} not found — cannot auto-fill env vars."))
            return _parse_env_file(env_path) if env_path.exists() else {}

        example_values = _parse_env_file(env_example_path)
        existing_values = _parse_env_file(env_path) if env_path.exists() else {}

        to_append: dict[str, str] = {}
        for key in AUTO_FILL_KEYS:
            if _has_env_var(key, existing_values):
                continue
            example_value = example_values.get(key)
            if not example_value:
                self.stdout.write(self.style.WARNING(f"  {key} missing from .env.example — skipping"))
                continue
            to_append[key] = example_value

        if to_append:
            _append_env_vars(env_path, to_append)
            existing_values.update(to_append)
            for key in to_append:
                self.stdout.write(self.style.SUCCESS(f"  Wrote {key} to .env"))
        else:
            self.stdout.write(self.style.SUCCESS("  All auto-shareable env vars already present."))

        return existing_values

    def _setup_oauth_app(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Setting up OAuth application..."))

        defaults = {
            "name": "Array Dev App",
            "client_type": OAuthApplication.CLIENT_PUBLIC,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": EXPECTED_REDIRECT_URIS,
            "algorithm": "RS256",
        }
        app, created = OAuthApplication.objects.get_or_create(
            client_id=ARRAY_APP_CLIENT_ID_DEV,
            defaults=defaults,
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"  Created OAuthApplication '{app.name}'"))
            return

        if app.redirect_uris != EXPECTED_REDIRECT_URIS:
            app.redirect_uris = EXPECTED_REDIRECT_URIS
            app.save(update_fields=["redirect_uris"])
            self.stdout.write(self.style.SUCCESS(f"  Updated redirect_uris on OAuthApplication '{app.name}'"))
        else:
            self.stdout.write(self.style.SUCCESS(f"  OAuthApplication '{app.name}' already exists."))

    def _setup_feature_flags(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Setting up feature flags..."))

        teams = Team.objects.all()
        if not teams.exists():
            self.stdout.write(self.style.WARNING("  No teams found — skipping feature flag creation."))
            return

        full_rollout_filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
        }

        for team in teams:
            # Use _base_manager to also see soft-deleted flags (the default `objects`
            # manager filters out deleted=True). Avoids an IntegrityError on re-run when
            # the flag was previously soft-deleted via the UI.
            existing = FeatureFlag._base_manager.filter(team=team, key="tasks").first()
            if existing is None:
                FeatureFlag.objects.create(
                    team=team,
                    key="tasks",
                    name="Background agents",
                    filters=full_rollout_filters,
                    active=True,
                    deleted=False,
                )
                self.stdout.write(self.style.SUCCESS(f"  Created 'tasks' flag for team {team.id} ({team.name})"))
            elif existing.deleted or not existing.active:
                existing.deleted = False
                existing.active = True
                existing.save(update_fields=["deleted", "active"])
                self.stdout.write(self.style.SUCCESS(f"  Restored 'tasks' flag for team {team.id} ({team.name})"))
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"  'tasks' flag already active for team {team.id} ({team.name}).")
                )

    def _build_skills(self):
        self.stdout.write(self.style.MIGRATE_HEADING("Building agent skills (this can take a minute)..."))

        process = subprocess.Popen(
            [sys.executable, "products/posthog_ai/scripts/build_skills.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            self.stdout.write(f"    {line.rstrip()}")
        return_code = process.wait()
        if return_code == 0:
            self.stdout.write(self.style.SUCCESS("  Skills built successfully."))
        else:
            self.stdout.write(self.style.ERROR(f"  Skills build failed (exit code {return_code})."))

    def _guide_github_app(self, env_file_values: dict[str, str]):
        missing = [k for k in GITHUB_APP_KEYS if not _has_env_var(k, env_file_values)]
        if not missing:
            self.stdout.write(self.style.MIGRATE_HEADING("GitHub App: all credentials present."))
            return

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("GitHub App setup needed"))
        self.stdout.write("  Each engineer needs their own dev GitHub App. Steps:")
        self.stdout.write(f"    1. Open: {GITHUB_APP_NEW_URL}")
        self.stdout.write(f"    2. Set the Setup URL (NOT Callback or Homepage) to: {GITHUB_APP_SETUP_URL}")
        self.stdout.write("    3. Permissions: Contents R/W, Pull requests R/W, Metadata R")
        self.stdout.write("    4. Generate a private key, install the app on your test repos")
        self.stdout.write("    5. Add to your .env (the slug is the URL-friendly name from the App URL):")
        self.stdout.write("")
        self.stdout.write('       GITHUB_APP_CLIENT_ID="your_app_id"')
        self.stdout.write('       GITHUB_APP_SLUG="your-app-slug"')
        self.stdout.write(
            '       GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\\n...\\n-----END RSA PRIVATE KEY-----"'
        )
        self.stdout.write("")

        if sys.stdin.isatty():
            try:
                answer = input("  Open the GitHub App creation page in your browser now? [y/N]: ").strip().lower()
            except EOFError:
                answer = ""
            if answer == "y":
                webbrowser.open(GITHUB_APP_NEW_URL)


_ENV_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _has_env_var(key: str, env_file_values: dict[str, str]) -> bool:
    """Return True if `key` is set in the live process env or in the parsed .env file."""
    return bool(os.environ.get(key)) or key in env_file_values


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a .env-style file into a dict. Strips matching surrounding quotes from the value."""
    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2)
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def _append_env_vars(env_path: Path, values: dict[str, str]) -> None:
    """Append key/value pairs to .env, creating the file if missing.

    Quotes values so they survive `set -o allexport; source .env` in hogli start.
    """
    needs_leading_newline = env_path.exists() and not env_path.read_text().endswith("\n")
    lines = []
    if needs_leading_newline:
        lines.append("")
    lines.append(f"# Added by setup_background_agents on {date.today().isoformat()}")
    for key, value in values.items():
        lines.append(f'{key}="{value}"')
    lines.append("")  # trailing newline
    with env_path.open("a") as f:
        f.write("\n".join(lines))
