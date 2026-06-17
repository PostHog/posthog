"""Per-user marketplace credential: mint / reuse / rotate the dedicated read-only key.

The Claude Code plugin marketplace is authenticated with a Project Secret API Key carried
as the git Basic password (see ``auth.py``). We deliberately scope that credential to one
**per user**, not one per team: a teammate connecting (or re-connecting) Claude Code mints
their *own* key, so rotating it only ever invalidates their own setup — never a colleague's
working install. The ``(team, label)`` uniqueness constraint on ``ProjectSecretAPIKey`` gives
us the per-user identity for free via a label keyed on the user id.

The raw token is unrecoverable after creation (only its hash + mask are stored), so "reuse"
means: return the existing key untouched when present, and only issue a fresh token when the
key is absent (create) or the caller explicitly asks to rotate (roll).
"""

from dataclasses import dataclass

from django.utils import timezone

from posthog.api.project_secret_api_key import MAX_PROJECT_SECRET_API_KEYS_PER_TEAM
from posthog.models import Team, User
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.utils import generate_random_token_secret, hash_key_value, mask_key_value

# Read-only: a leaked marketplace credential can only read this team's skills, nothing else.
MARKETPLACE_CREDENTIAL_SCOPES = ["llm_skill:read"]

# Deterministic per (team, user) — fits the 40-char label cap (prefix + an int user id).
_LABEL_PREFIX = "Skill store · "


class MarketplaceCredentialLimitError(Exception):
    """Raised when the team is already at the Project Secret API Key cap."""


@dataclass(frozen=True)
class IssuedMarketplaceCredential:
    key: ProjectSecretAPIKey
    # The raw ``phs_`` token, available only when we just minted or rotated. None when the
    # existing key was returned untouched (its token is unrecoverable).
    token: str | None
    status: str  # "created" | "rotated" | "exists"


def marketplace_credential_label(user_id: int) -> str:
    return f"{_LABEL_PREFIX}{user_id}"


def get_marketplace_credential(team: Team, user: User) -> ProjectSecretAPIKey | None:
    return ProjectSecretAPIKey.objects.filter(team=team, label=marketplace_credential_label(user.id)).first()


def issue_marketplace_credential(team: Team, user: User, *, rotate: bool) -> IssuedMarketplaceCredential:
    """Reuse the user's marketplace key when present; create if absent, roll only if ``rotate``."""
    existing = get_marketplace_credential(team, user)
    if existing is not None and not rotate:
        return IssuedMarketplaceCredential(key=existing, token=None, status="exists")

    raw_token = generate_random_token_secret()
    if existing is None:
        if ProjectSecretAPIKey.objects.filter(team=team).count() >= MAX_PROJECT_SECRET_API_KEYS_PER_TEAM:
            raise MarketplaceCredentialLimitError(
                f"This project already has the maximum of {MAX_PROJECT_SECRET_API_KEYS_PER_TEAM} secret API keys. "
                "Remove an unused key before connecting."
            )
        key = ProjectSecretAPIKey.objects.create(
            team=team,
            secure_value=hash_key_value(raw_token),
            mask_value=mask_key_value(raw_token),
            created_by=user,
            label=marketplace_credential_label(user.id),
            scopes=list(MARKETPLACE_CREDENTIAL_SCOPES),
        )
        return IssuedMarketplaceCredential(key=key, token=raw_token, status="created")

    existing.secure_value = hash_key_value(raw_token)
    existing.mask_value = mask_key_value(raw_token)
    existing.last_rolled_at = timezone.now()
    existing.save(update_fields=["secure_value", "mask_value", "last_rolled_at"])
    return IssuedMarketplaceCredential(key=existing, token=raw_token, status="rotated")


def marketplace_repo_url(team_id: int, host: str, scheme: str) -> str:
    """The marketplace git repo URL with no credential embedded — safe to display."""
    return f"{scheme}://{host}/api/projects/{team_id}/llm_skills/marketplace.git"


def _marketplace_git_url(team_id: int, host: str, scheme: str, token: str | None) -> str:
    credential = token or "YOUR_PHS_TOKEN"
    return f"{scheme}://x-access-token:{credential}@{host}/api/projects/{team_id}/llm_skills/marketplace.git"


def build_install_command(team_id: int, host: str, scheme: str, token: str | None) -> str:
    """Claude Code: the ``/plugin marketplace add`` command. Embeds the token, or a placeholder."""
    return f"/plugin marketplace add {_marketplace_git_url(team_id, host, scheme, token)}"


def build_codex_install_command(
    team_id: int, host: str, scheme: str, token: str | None, *, plugin_name: str, marketplace_name: str
) -> str:
    """OpenAI Codex: add the same git marketplace, then install the plugin (two lines).

    The marketplace is the identical git endpoint Claude Code clones — Codex reads our
    ``.claude-plugin/marketplace.json`` directly (verified against codex-cli), so no Codex-specific
    manifest is needed. Codex's git source requires ``https`` in practice.
    """
    add = f'codex plugin marketplace add "{_marketplace_git_url(team_id, host, scheme, token)}"'
    install = f"codex plugin add {plugin_name}@{marketplace_name}"
    return f"{add}\n{install}"
