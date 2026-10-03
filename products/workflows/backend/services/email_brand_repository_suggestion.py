import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from urllib.parse import urlparse

from django.db import models
from django.utils import timezone

import structlog
import tldextract

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.team import Team

logger = structlog.get_logger(__name__)

SUGGESTION_LIMIT = 5
RECENT_PUSH_WINDOW = timedelta(days=30)
WEB_LANGUAGES = frozenset({"TypeScript", "JavaScript", "Vue", "Svelte", "Astro", "HTML", "CSS", "SCSS", "MDX"})
MIN_TOKEN_LENGTH = 3
GENERIC_TOKENS = frozenset(
    {
        "www",
        "app",
        "web",
        "api",
        "dev",
        "staging",
        "localhost",
        "default",
        "project",
        "the",
        "inc",
        "llc",
        "ltd",
        "gmbh",
        "corp",
        "company",
    }
)
NEVER_PUSHED = datetime.min.replace(tzinfo=UTC)
# Private suffixes too, so hosting domains such as vercel.app or github.io never count as brand words.
DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)


class RepositorySuggestionReason(models.TextChoices):
    NAME_MATCH = "name_match", "Name match"
    RECENT_PUSH = "recent_push", "Recent push"
    WEB_LANGUAGE = "web_language", "Web language"


@frozen
class RepositorySuggestion:
    id: int
    name: str
    full_name: str
    language: str | None
    pushed_at: str | None
    reasons: tuple[RepositorySuggestionReason, ...]


@frozen
class RepositorySuggestions:
    integration_id: int | None
    repositories: tuple[RepositorySuggestion, ...]


def _github_integration(team: Team, integration_id: int | None) -> Integration | None:
    integrations = Integration.objects.filter(team_id=team.id, kind="github").order_by("created_at", "id")
    if integration_id is not None:
        integrations = integrations.filter(id=integration_id)
    return integrations.first()


def _cached_repositories(integration: Integration) -> list[dict]:
    github = GitHubIntegration(integration, source="workflows_brand", priority=Priority.NORMAL)
    try:
        return github.list_all_cached_repositories()
    except Exception:
        # The picker loads the same list and shows its own error, so the flow only loses its preselection.
        logger.warning("email_brand.repository_suggestion.list_failed", integration_id=integration.id, exc_info=True)
        return []


def _hostname(url: str) -> str:
    try:
        return urlparse(url if "://" in url else f"https://{url}").hostname or ""
    except ValueError:
        return ""


def _is_ip_address(host: str) -> bool:
    try:
        ip_address(host)
    except ValueError:
        return False
    return True


def _host_without_suffix(url: str) -> str:
    host = _hostname(url)
    if _is_ip_address(host):
        return ""
    parts = DOMAIN_PARTS(host)
    if parts.suffix:
        return f"{parts.subdomain}.{parts.domain}"
    return host.rsplit(".", 1)[0]


def _tokens(texts: Iterable[str]) -> set[str]:
    words = {word for text in texts for word in re.split(r"[^a-z0-9]+", text.casefold())}
    return {word for word in words if len(word) >= MIN_TOKEN_LENGTH and word not in GENERIC_TOKENS}


def _brand_tokens(team: Team) -> set[str]:
    hosts = (_host_without_suffix(url) for url in team.app_urls or [] if url)
    return _tokens([*hosts, team.project.name, team.organization.name])


def _name_overlap(repository: dict, brand_tokens: set[str]) -> int:
    name = repository["name"]
    compact_name = re.sub(r"[^a-z0-9]+", "", name.casefold())
    return len((_tokens([name]) | {compact_name}) & brand_tokens)


def _pushed_at(repository: dict) -> datetime:
    try:
        pushed_at = datetime.fromisoformat(repository["pushed_at"])
    except (KeyError, TypeError, ValueError):
        return NEVER_PUSHED
    return pushed_at if pushed_at.tzinfo else pushed_at.replace(tzinfo=UTC)


def _reasons(repository: dict, brand_tokens: set[str], now: datetime) -> tuple[RepositorySuggestionReason, ...]:
    checks = {
        RepositorySuggestionReason.NAME_MATCH: _name_overlap(repository, brand_tokens) > 0,
        RepositorySuggestionReason.RECENT_PUSH: now - _pushed_at(repository) <= RECENT_PUSH_WINDOW,
        RepositorySuggestionReason.WEB_LANGUAGE: repository.get("language") in WEB_LANGUAGES,
    }
    return tuple(reason for reason, applies in checks.items() if applies)


def _suggestion(repository: dict, brand_tokens: set[str], now: datetime) -> RepositorySuggestion:
    return RepositorySuggestion(
        id=repository["id"],
        name=repository["name"],
        full_name=repository["full_name"],
        language=repository.get("language"),
        pushed_at=repository.get("pushed_at"),
        reasons=_reasons(repository, brand_tokens, now),
    )


def suggest_repositories(team: Team, integration_id: int | None = None) -> RepositorySuggestions:
    integration = _github_integration(team, integration_id)
    if integration is None:
        return RepositorySuggestions(integration_id=None, repositories=())
    brand_tokens = _brand_tokens(team)
    now = timezone.now()
    ranked = sorted(
        (repository for repository in _cached_repositories(integration) if not repository.get("archived", False)),
        key=lambda repository: (
            -_name_overlap(repository, brand_tokens),
            -_pushed_at(repository).timestamp(),
            repository["full_name"].casefold(),
        ),
    )
    return RepositorySuggestions(
        integration_id=integration.id,
        repositories=tuple(_suggestion(repository, brand_tokens, now) for repository in ranked[:SUGGESTION_LIMIT]),
    )
