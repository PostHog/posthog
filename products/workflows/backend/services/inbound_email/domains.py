"""Which domains a team receives mail on: its ready-made address, and subdomains it proved with an MX record.

The MX host is shared by every SES customer in a region, so an MX record alone proves little. A custom domain also
needs a verified sending domain of the same team to cover it, and only one project of an organization can claim it.
"""

import re
import secrets
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models.integration import EmailIntegration
from posthog.models.team import Team

from products.workflows.backend.facade.contracts import InboundDomainError
from products.workflows.backend.facade.enums import (
    InboundEmailDomainKind as Kind,
    InboundEmailDomainStatus as Status,
)
from products.workflows.backend.models import InboundEmailDomain
from products.workflows.backend.services.email_domain_dns import MxLookup, lookup_mx

logger = structlog.get_logger(__name__)

DEFAULT_SUBDOMAIN = "inbound"
# Long enough that DNS and SES problems pass, and that an active row demoted for them is no longer fresh below.
CHECK_FAILURE_GRACE = timedelta(days=2)
PENDING_ACTIVATION_WINDOW = timedelta(days=2)
SWEEP_BATCH_SIZE = 200
_HOSTNAME = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_ADJECTIVES = (
    "amber",
    "brave",
    "calm",
    "clever",
    "eager",
    "gentle",
    "golden",
    "happy",
    "jolly",
    "kind",
    "lively",
    "merry",
    "misty",
    "quiet",
    "rapid",
    "silver",
    "sunny",
    "swift",
    "tidy",
    "witty",
)
_NOUNS = (
    "badger",
    "beaver",
    "comet",
    "falcon",
    "fern",
    "harbor",
    "hedgehog",
    "heron",
    "lantern",
    "maple",
    "meadow",
    "otter",
    "pebble",
    "puffin",
    "quail",
    "river",
    "sparrow",
    "thistle",
    "walnut",
    "willow",
)


@frozen
class DomainPreflight:
    domain: str
    eligible: bool
    reason: str
    verified_parent: str
    whole_domain: bool
    existing_mx: tuple[str, ...]
    points_here: bool
    dns_answered: bool


@frozen
class MxCheck:
    domain: InboundEmailDomain
    state: str
    found: tuple[str, ...]


def normalize_domain(value: str) -> str:
    return value.strip().lower().rstrip(".")


def expected_mx_host() -> str:
    return settings.WORKFLOWS_INBOUND_EMAIL_MX_HOST


def generated_addresses_available() -> bool:
    return bool(settings.WORKFLOWS_INBOUND_EMAIL_BASE_DOMAIN)


def verified_sending_domains(team_id: int) -> list[str]:
    rows = IntegrationManager.email.any.list(team_id, where={"verified": True})
    return sorted({normalize_domain(row.config["domain"]) for row in rows if row.config.get("domain")})


def has_verified_parent(domain: InboundEmailDomain) -> bool:
    return domain.kind == Kind.GENERATED or bool(_verified_parent(domain.team_id, domain.domain))


def _verified_parent(team_id: int, domain: str) -> str:
    return next((p for p in verified_sending_domains(team_id) if domain == p or domain.endswith(f".{p}")), "")


def ensure_generated_domain(team_id: int, *, created_by_id: int | None) -> InboundEmailDomain:
    existing = InboundEmailDomain.objects.for_team(team_id).filter(kind=Kind.GENERATED).first()
    return existing or _create_generated_domain(team_id, created_by_id)


def rotate_generated_domain(team_id: int, *, created_by_id: int | None) -> InboundEmailDomain:
    """Mail to the old address stops being accepted. Already received mail stays."""
    with transaction.atomic():
        InboundEmailDomain.objects.for_team(team_id).filter(kind=Kind.GENERATED).delete()
        return _create_generated_domain(team_id, created_by_id)


def _create_generated_domain(team_id: int, created_by_id: int | None) -> InboundEmailDomain:
    if not generated_addresses_available():
        raise InboundDomainError("unavailable", "Ready-made addresses aren't available on this instance.")
    last_error: IntegrityError | None = None
    for _ in range(5):
        slug = f"{secrets.choice(_ADJECTIVES)}-{secrets.choice(_NOUNS)}-{secrets.token_hex(3)}"
        try:
            with transaction.atomic():
                return InboundEmailDomain.objects.for_team(team_id).create(
                    team_id=team_id,
                    domain=f"{slug}.{settings.WORKFLOWS_INBOUND_EMAIL_BASE_DOMAIN}",
                    kind=Kind.GENERATED,
                    status=Status.ACTIVE,
                    activated_at=timezone.now(),
                    created_by_id=created_by_id,
                )
        except IntegrityError as error:
            # A concurrent request may have created the team's address, which is the row this call wants.
            existing = InboundEmailDomain.objects.for_team(team_id).filter(kind=Kind.GENERATED).first()
            if existing:
                return existing
            last_error = error
    raise InboundDomainError("unavailable", "Couldn't create an address. Try again.") from last_error


def preflight_domain(team_id: int, value: str) -> DomainPreflight:
    domain = normalize_domain(value)
    if not _HOSTNAME.match(domain):
        return _ineligible(domain, "Enter a domain such as inbound.example.com.")
    if _is_generated_namespace(domain):
        return _ineligible(domain, "This domain is reserved for ready-made addresses.")
    parent = _verified_parent(team_id, domain)
    if not parent:
        return _ineligible(
            domain,
            "This domain isn't a verified sending domain of this project, or a subdomain of one. "
            "Verify the domain for sending first.",
        )
    taken = InboundEmailDomain.objects.unscoped().filter(domain=domain, status=Status.ACTIVE).exclude(team_id=team_id)
    for holder in taken:
        if has_verified_parent(holder):
            return _ineligible(domain, "Another project already receives mail on this domain.", parent)
        retire_domain(holder)
    own_row = InboundEmailDomain.objects.for_team(team_id).filter(domain=domain).first()
    if _earlier_claim_in_organization(team_id, domain, own_row) is not None:
        return _ineligible(
            domain,
            "Another project in this organization already claimed this domain. Remove it there to use it here.",
            parent,
        )
    lookup = lookup_mx(domain)
    return DomainPreflight(
        domain=domain,
        eligible=True,
        reason="",
        verified_parent=parent,
        whole_domain=domain == parent,
        existing_mx=_foreign_hosts(lookup),
        points_here=_points_here(lookup),
        dns_answered=lookup.answered,
    )


def create_custom_domain(
    team_id: int, value: str, *, confirm_move_mail: bool, created_by_id: int | None
) -> InboundEmailDomain:
    preflight = preflight_domain(team_id, value)
    if not preflight.eligible:
        raise InboundDomainError("not_eligible", preflight.reason)
    if (preflight.whole_domain or preflight.existing_mx) and not confirm_move_mail:
        raise InboundDomainError(
            "confirmation_required",
            "This moves all mail for the domain to PostHog. Confirm that you want this, or forward mail instead.",
        )
    domain, _ = InboundEmailDomain.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        domain=preflight.domain,
        defaults={"kind": Kind.CUSTOM, "status": Status.PENDING, "created_by_id": created_by_id},
    )
    return domain


def check_domain_mx(domain: InboundEmailDomain) -> MxCheck:
    """Activate the domain once it is still its team's and public DNS sends its mail to us.

    A failed lookup changes nothing, and a failed check only demotes an active domain once it has failed for a while.
    """
    if domain.kind == Kind.GENERATED:
        return MxCheck(domain=domain, state="active", found=())
    if not has_verified_parent(domain):
        retire_domain(domain)
        return MxCheck(domain=domain, state="no_sending_domain", found=())
    if (
        domain.status != Status.ACTIVE
        and _earlier_claim_in_organization(domain.team_id, domain.domain, domain) is not None
    ):
        return MxCheck(domain=domain, state="taken", found=())
    lookup = lookup_mx(domain.domain)
    now = timezone.now()
    if not lookup.answered:
        InboundEmailDomain.objects.for_team(domain.team_id).filter(pk=domain.pk).update(mx_checked_at=now)
        domain.mx_checked_at = now
        return MxCheck(domain=domain, state="lookup_failed", found=())
    found = tuple(f"{preference} {host}" for preference, host in lookup.records)
    state = _mx_state(lookup)
    if state != "active":
        _record_failed_check(domain, now)
        return MxCheck(domain=domain, state=state, found=found)
    try:
        with transaction.atomic():
            InboundEmailDomain.objects.for_team(domain.team_id).filter(pk=domain.pk).update(
                mx_checked_at=now,
                status=Status.ACTIVE,
                activated_at=domain.activated_at or now,
            )
    except IntegrityError:
        return MxCheck(domain=domain, state="taken", found=found)
    domain.mx_checked_at, domain.status, domain.activated_at = now, Status.ACTIVE, domain.activated_at or now
    return MxCheck(domain=domain, state="active", found=found)


def retire_domain(domain: InboundEmailDomain) -> None:
    """Stop routing a domain no verified sending domain of its team covers. It only returns through a new check."""
    if domain.status == Status.PENDING and domain.checks_failing_since is None:
        return
    fields = {"status": Status.PENDING, "activated_at": None, "checks_failing_since": None}
    InboundEmailDomain.objects.for_team(domain.team_id).filter(pk=domain.pk).update(**fields)
    domain.status, domain.activated_at, domain.checks_failing_since = Status.PENDING, None, None


def may_activate_on_arrival(domain: InboundEmailDomain, candidates: Sequence[InboundEmailDomain]) -> bool:
    """Only a claim someone just made and no other project shares. Any other pending row waits for its owner to check."""
    if timezone.now() - domain.created_at > PENDING_ACTIVATION_WINDOW:
        return False
    return not any(other.domain == domain.domain and other.pk != domain.pk for other in candidates)


def sweep_active_domains(limit: int = SWEEP_BATCH_SIZE) -> int:
    """Recheck the active custom domains checked longest ago, so domains that receive no mail get retired too."""
    rows = list(
        InboundEmailDomain.objects.unscoped()
        .filter(kind=Kind.CUSTOM, status=Status.ACTIVE)
        .order_by(F("mx_checked_at").asc(nulls_first=True))[:limit]
    )
    for row in rows:
        try:
            _sweep_domain(row)
        except Exception:
            # One domain's DNS or SES failure must not stop the others from being checked.
            logger.warning("inbound_email_domain_sweep_failed", domain_id=str(row.pk), exc_info=True)
    return len(rows)


def _sweep_domain(domain: InboundEmailDomain) -> None:
    # A stored `verified` flag never goes back to false, so only SES can say the sending domain was lost.
    lost = _sending_domain_lost(domain)
    if check_domain_mx(domain).state != "active":
        return
    # Only a whole passing sweep clears a failure. A check a person requests can't keep a lost domain receiving.
    if lost:
        _record_failed_check(domain, timezone.now())
    elif domain.checks_failing_since is not None:
        InboundEmailDomain.objects.for_team(domain.team_id).filter(pk=domain.pk).update(checks_failing_since=None)
        domain.checks_failing_since = None


def _sending_domain_lost(domain: InboundEmailDomain) -> bool:
    parent = _verified_parent(domain.team_id, domain.domain)
    rows = IntegrationManager.email.any.list(domain.team_id, where={"verified": True})
    reports = [
        EmailIntegration(row).status(refresh=True)
        for row in rows
        if normalize_domain(row.config.get("domain", "")) == parent
    ]
    return bool(reports) and all(
        report.check.every_dns_lookup_answered and not report.check.is_verified for report in reports
    )


def _record_failed_check(domain: InboundEmailDomain, now: datetime) -> None:
    fields: dict[str, Any] = {"mx_checked_at": now}
    if domain.status == Status.ACTIVE:
        fields["checks_failing_since"] = domain.checks_failing_since or now
        if now - fields["checks_failing_since"] >= CHECK_FAILURE_GRACE:
            fields.update(status=Status.PENDING, activated_at=None, checks_failing_since=None)
    InboundEmailDomain.objects.for_team(domain.team_id).filter(pk=domain.pk).update(**fields)
    for name, value in fields.items():
        setattr(domain, name, value)


def _earlier_claim_in_organization(
    team_id: int, name: str, domain: InboundEmailDomain | None = None
) -> InboundEmailDomain | None:
    """The oldest claim on the name by another project of this organization whose sending domain still covers it."""
    teams_in_organization = Team.objects.filter(
        organization_id=Team.objects.only("organization_id").get(pk=team_id).organization_id
    ).values_list("pk", flat=True)
    claims = (
        InboundEmailDomain.objects.unscoped()
        .filter(domain=name, team_id__in=list(teams_in_organization))
        .exclude(team_id=team_id)
    )
    if domain is not None:
        claims = claims.filter(created_at__lt=domain.created_at)
    return next((claim for claim in claims.order_by("created_at") if has_verified_parent(claim)), None)


def domains_for_recipients(recipients: Iterable[str]) -> list[InboundEmailDomain]:
    names = {recipient.rpartition("@")[2] for recipient in recipients if "@" in recipient}
    # Team scope comes from the rows themselves: this is the routing step that decides which team a message is for.
    return list(InboundEmailDomain.objects.unscoped().filter(domain__in=names))


def _mx_state(lookup: MxLookup) -> str:
    if not _points_here(lookup):
        return "conflict" if lookup.records else "missing"
    ours = min(preference for preference, host in lookup.records if host == expected_mx_host())
    # Senders try the lowest value first, so a tie or a lower value on another host takes the mail.
    outranked = any(preference <= ours and host != expected_mx_host() for preference, host in lookup.records)
    return "conflict" if outranked else "active"


def _points_here(lookup: MxLookup) -> bool:
    return any(host == expected_mx_host() for _, host in lookup.records)


def _foreign_hosts(lookup: MxLookup) -> tuple[str, ...]:
    return tuple(host for _, host in lookup.records if host != expected_mx_host())


def _is_generated_namespace(domain: str) -> bool:
    base = settings.WORKFLOWS_INBOUND_EMAIL_BASE_DOMAIN
    return bool(base) and (domain == base or domain.endswith(f".{base}"))


def _ineligible(domain: str, reason: str, parent: str = "") -> DomainPreflight:
    return DomainPreflight(
        domain=domain,
        eligible=False,
        reason=reason,
        verified_parent=parent,
        whole_domain=False,
        existing_mx=(),
        points_here=False,
        dns_answered=True,
    )
