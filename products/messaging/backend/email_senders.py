from collections.abc import Iterable, Mapping
from typing import Any, Final

from django.db import models

from rest_framework import serializers
from rest_framework.pagination import LimitOffsetPagination

from posthog.cdp.validation import parse_email_sender_ids
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
    """Every address an email can go out from, by the rule the send path uses.

    An override address wins. Otherwise each integration the send can pick resolves to its address, in
    order, skipping ids that no longer resolve. A legacy plain-string `from` is the address itself.
    """
    if isinstance(from_value, str):
        return ResolvedEmailSender(addresses=(from_value,) if from_value else (), name=None, integration_ids=())
    if not isinstance(from_value, dict):
        return ResolvedEmailSender(addresses=(), name=None, integration_ids=())

    integration_ids = parse_email_sender_ids(from_value).selectable
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


class ListRowPagination(LimitOffsetPagination):
    """Page size for the slim list endpoints, which the web app loads in full by following `next`."""

    default_limit = 500
    max_limit = 1000


_EMAIL_SENDER_INTEGRATIONS_CONTEXT_KEY: Final = "email_sender_integrations"


def email_senders_from_context(context: Mapping[str, Any]) -> Mapping[int, EmailSenderIntegration]:
    # Raises KeyError when the row is serialized without EmailSenderPrefetchListSerializer, which is
    # the only place the map is loaded. Loading it per row instead would be one query per row.
    return context[_EMAIL_SENDER_INTEGRATIONS_CONTEXT_KEY]


class EmailSenderPrefetchListSerializer(serializers.ListSerializer):
    """Loads the email sender integrations every row on the page names, in one team-scoped query."""

    def sender_from_values(self, row: Any) -> Iterable[Any]:
        raise NotImplementedError

    def to_representation(self, data: Any) -> list[Any]:
        rows = list(data.all() if isinstance(data, models.manager.BaseManager) else data)
        integration_ids = {
            integration_id
            for row in rows
            for from_value in self.sender_from_values(row)
            for integration_id in parse_email_sender_ids(from_value).selectable
        }
        self.context[_EMAIL_SENDER_INTEGRATIONS_CONTEXT_KEY] = load_email_sender_integrations(
            self.context["get_team"]().id, integration_ids
        )
        return super().to_representation(rows)
