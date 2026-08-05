"""Per-user marketplace credential: mint / reuse / rotate a dedicated, scoped Personal API Key.

The Claude Code / Codex plugin marketplace is authenticated with the credential carried as the
git Basic password (see ``auth.py``). We use a **Personal API Key** — a dedicated, read-only one
scoped to ``llm_skill:read`` and locked to a single team — rather than a Project Secret API Key.

Why a Personal API Key: it's tied to the user, so its access is re-evaluated against current
membership on every request. The moment the user is offboarded (or loses team access), the
standard permission stack on the marketplace viewset denies the clone — the credential is
"revoked" automatically, no manual cleanup. A Project Secret API Key is deliberately user-less
(built to outlive the people who made it), which is exactly the wrong property here.

It's still *dedicated and read-only* (not the user's everyday key): one minted-for-this-purpose
key per (user, team), scoped to only ``llm_skill:read`` and that one team. The raw token is
unrecoverable after creation, so "reuse" means return-if-present / roll-if-asked.
"""

from dataclasses import dataclass
from urllib.parse import quote

from django.db import transaction
from django.utils import timezone

from posthog.models import PersonalAPIKey, Team, User
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value
from posthog.utils import absolute_uri

# Read-only: a leaked credential can only read this one team's skills, nothing else.
MARKETPLACE_CREDENTIAL_SCOPES = ["llm_skill:read"]

# One key per (user, team). The Personal API Key is owned by the user, so the label only needs to
# disambiguate teams; it's shown in the user's API-keys settings. Fits the 40-char label cap.
_LABEL_PREFIX = "Skill store · team "


@dataclass(frozen=True)
class IssuedMarketplaceCredential:
    key: PersonalAPIKey
    # The raw ``phx_`` token, available only when we just minted or rotated. None when the
    # existing key was returned untouched (its token is unrecoverable).
    token: str | None
    status: str  # "created" | "rotated" | "exists"


def marketplace_credential_label(team_id: int) -> str:
    return f"{_LABEL_PREFIX}{team_id}"


def get_marketplace_credential(team: Team, user: User) -> PersonalAPIKey | None:
    return PersonalAPIKey.objects.filter(user=user, label=marketplace_credential_label(team.id)).first()


def issue_marketplace_credential(team: Team, user: User, *, rotate: bool) -> IssuedMarketplaceCredential:
    """Reuse the user's marketplace key when present; create if absent, roll only if ``rotate``.

    The row is taken with ``select_for_update`` so concurrent rotations of the same key serialize
    — without it, two ``rotate=True`` requests would each store a different token and the loser's
    returned token would silently never match the stored hash.
    """
    label = marketplace_credential_label(team.id)
    with transaction.atomic():
        existing = PersonalAPIKey.objects.select_for_update().filter(user=user, label=label).first()
        if existing is not None and not rotate:
            # Re-narrow before handing it back: a same-label key that drifted to broader scopes
            # would otherwise be returned while the endpoint/UI describe it as read-only and
            # team-scoped. Narrowing needs no new token, so this stays "exists".
            narrowed_fields = _narrow_to_marketplace_scope(existing, team)
            if narrowed_fields:
                existing.save(update_fields=narrowed_fields)
            return IssuedMarketplaceCredential(key=existing, token=None, status="exists")

        raw_token = generate_random_token_personal()
        if existing is None:
            key = PersonalAPIKey.objects.create(
                user=user,
                label=label,
                secure_value=hash_key_value(raw_token),
                mask_value=mask_key_value(raw_token),
                scopes=list(MARKETPLACE_CREDENTIAL_SCOPES),
                scoped_teams=[team.id],
                scoped_organizations=[],
            )
            return IssuedMarketplaceCredential(key=key, token=raw_token, status="created")

        existing.secure_value = hash_key_value(raw_token)
        existing.mask_value = mask_key_value(raw_token)
        existing.last_used_at = None
        existing.last_rolled_at = timezone.now()
        # Rotation re-mints the token, so re-assert the narrow scoping in the same write — a freshly
        # minted token must never inherit scopes broader than what we advertise as read-only.
        update_fields = ["secure_value", "mask_value", "last_used_at", "last_rolled_at"]
        update_fields += _narrow_to_marketplace_scope(existing, team)
        existing.save(update_fields=update_fields)
        return IssuedMarketplaceCredential(key=existing, token=raw_token, status="rotated")


def _narrow_to_marketplace_scope(key: PersonalAPIKey, team: Team) -> list[str]:
    """Force ``key`` onto the canonical read-only, single-team scoping. Returns the field names
    that actually changed (so callers can pass them to ``save(update_fields=...)``)."""
    canonical: dict[str, list[str] | list[int]] = {
        "scopes": list(MARKETPLACE_CREDENTIAL_SCOPES),
        "scoped_teams": [team.id],
        "scoped_organizations": [],
    }
    changed: list[str] = []
    for field, value in canonical.items():
        if getattr(key, field) != value:
            setattr(key, field, value)
            changed.append(field)
    return changed


# Placeholder shown in the command template before a token is minted (and never sent to a server).
_TOKEN_PLACEHOLDER = "YOUR_PHX_TOKEN"


def marketplace_repo_url(team_id: int) -> str:
    """The marketplace git repo URL with no credential embedded — safe to display.

    Pinned to ``SITE_URL`` via ``absolute_uri`` (not ``request.get_host()``): the host must not be
    steerable by a request Host header, since the install command below embeds a live token.
    """
    return absolute_uri(f"/api/projects/{team_id}/llm_skills/marketplace.git")


def _credentialed_git_url(team_id: int, token: str | None) -> str:
    credential = quote(token, safe="") if token else _TOKEN_PLACEHOLDER
    scheme, sep, rest = marketplace_repo_url(team_id).partition("://")
    return f"{scheme}{sep}x-access-token:{credential}@{rest}"


def build_install_command(team_id: int, token: str | None, *, plugin_name: str, marketplace_name: str) -> str:
    """Claude Code: add the marketplace, then install the plugin (two slash commands)."""
    add = f"/plugin marketplace add {_credentialed_git_url(team_id, token)}"
    install = f"/plugin install {plugin_name}@{marketplace_name}"
    return f"{add}\n{install}"


def build_codex_install_command(team_id: int, token: str | None, *, plugin_name: str, marketplace_name: str) -> str:
    """OpenAI Codex: add the same git marketplace, then install the plugin (two lines)."""
    add = f'codex plugin marketplace add "{_credentialed_git_url(team_id, token)}"'
    install = f"codex plugin add {plugin_name}@{marketplace_name}"
    return f"{add}\n{install}"
