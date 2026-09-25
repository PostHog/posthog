from collections.abc import Iterable, Mapping
from typing import Any

from posthog.dataclasses import frozen
from posthog.models.integration import Integration


@frozen
class EmailSenderIntegration:
    email: str
    name: str | None


@frozen
class ResolvedEmailSender:
    addresses: tuple[str, ...]
    name: str | None
    integration_ids: tuple[int, ...]


def sender_integration_ids(from_value: Any) -> tuple[int, ...]:
    """The integration ids an email `from` value names: `integrationId`, then the `integrationIds` rotation."""
    if not isinstance(from_value, dict):
        return ()
    rotation = from_value.get("integrationIds")
    candidates = [from_value.get("integrationId"), *(rotation if isinstance(rotation, list) else [])]
    return tuple(
        dict.fromkeys(
            candidate for candidate in candidates if isinstance(candidate, int) and not isinstance(candidate, bool)
        )
    )


def load_email_sender_integrations(team_id: int, integration_ids: Iterable[int]) -> dict[int, EmailSenderIntegration]:
    # Integration ids are global, so the team filter is what stops a step naming another team's sender
    # from resolving to that team's address.
    ids = set(integration_ids)
    if not ids:
        return {}
    senders: dict[int, EmailSenderIntegration] = {}
    for integration_id, config in Integration.objects.filter(team_id=team_id, kind="email", id__in=ids).values_list(
        "id", "config"
    ):
        email = config.get("email") if isinstance(config, dict) else None
        if isinstance(email, str) and email:
            name = config.get("name")
            senders[integration_id] = EmailSenderIntegration(email=email, name=name if isinstance(name, str) else None)
    return senders


def resolve_email_sender(from_value: Any, integrations: Mapping[int, EmailSenderIntegration]) -> ResolvedEmailSender:
    """Every address an email can go out from.

    An override address wins. Otherwise each sender integration resolves to its address, in order,
    skipping ids that no longer resolve. A legacy plain-string `from` is the address itself.
    """
    if isinstance(from_value, str):
        return ResolvedEmailSender(addresses=(from_value,) if from_value else (), name=None, integration_ids=())
    if not isinstance(from_value, dict):
        return ResolvedEmailSender(addresses=(), name=None, integration_ids=())

    integration_ids = sender_integration_ids(from_value)
    resolved = [integrations[integration_id] for integration_id in integration_ids if integration_id in integrations]

    override = from_value.get("email")
    if isinstance(override, str) and override:
        addresses: tuple[str, ...] = (override,)
    else:
        addresses = tuple(dict.fromkeys(sender.email for sender in resolved))

    name = from_value.get("name")
    if not (isinstance(name, str) and name):
        name = resolved[0].name if resolved else None
    return ResolvedEmailSender(addresses=addresses, name=name, integration_ids=integration_ids)
