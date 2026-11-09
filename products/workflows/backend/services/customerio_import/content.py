"""What an import needs beyond the automation graph: message content, senders, categories and segment names.

The caller can pass all of it. When it leaves out message content and the team stored a Customer.io App API key
(the opt-out import saves one), PostHog reads the content itself, so an agent passes only the graph.
"""

import json
from typing import Any

import structlog

from posthog.integrations import IntegrationManager

from products.messaging.backend.facade.categories import list_categories
from products.workflows.backend.facade.contracts import (
    CampaignSource,
    ImportCategory,
    ImportContent,
    ImportNote,
    ImportOptions,
    ImportSegment,
    ImportSender,
)
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel
from products.workflows.backend.services.customerio_import.app_api import CustomerioApiError, CustomerioAppApi

logger = structlog.get_logger(__name__)

_MESSAGE_ACTION_TYPES = {"email_action", "webhook_action", "attribute_update_action", "create_event_action"}


def import_content(
    team_id: int,
    sources: list[CampaignSource],
    options: ImportOptions,
    sender_identities: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    deadline: float,
    left_alone: frozenset[str] = frozenset(),
) -> ImportContent:
    sender_addresses = {**_identity_addresses(sender_identities), **options.sender_addresses}
    segment_info = {**_segment_info(segments), **options.segments}
    snippets = options.snippets
    fetch_notes: dict[str, tuple[ImportNote, ...]] = {}
    fetched = False

    # An automation the import will leave unchanged needs no content, so it costs no reads.
    missing = {
        id(source)
        for source in sources
        if _misses_templates(source) and str(source.campaign.get("id")) not in left_alone
    }
    api_key = _stored_app_api_key(team_id) if missing else None
    if api_key:
        api = CustomerioAppApi(api_key, deadline=deadline)
        try:
            if not sender_addresses:
                sender_addresses = _identity_addresses(api.sender_identities())
            if not segment_info:
                segment_info = _segment_info(api.segments())
            if not snippets:
                snippets = _snippet_values(api.snippets())
        except CustomerioApiError as error:
            logger.info("workflows.import.customerio_lookup_failed", team_id=team_id, status=error.status)
        filled: list[CampaignSource] = []
        for source in sources:
            if id(source) not in missing:
                filled.append(source)
                continue
            try:
                filled.append(_with_fetched_templates(source, api.campaign_actions(str(source.campaign.get("id")))))
                fetched = True
            except CustomerioApiError as error:
                fetch_notes[str(source.campaign.get("id"))] = (
                    ImportNote(
                        level=WorkflowImportNoteLevel.NEEDS_INPUT,
                        message=f"PostHog could not read this automation's messages from Customer.io: {error} "
                        "Import again with its templates.",
                    ),
                )
                filled.append(source)
        sources = filled

    return ImportContent(
        sources=sources,
        options=ImportOptions(
            snippets=snippets,
            segment_cohorts=options.segment_cohorts,
            layouts=options.layouts,
            sender_addresses=sender_addresses,
            senders=options.senders or _team_senders(team_id),
            topic_categories=options.topic_categories or _topic_categories(team_id),
            segments=segment_info,
        ),
        fetch_notes=fetch_notes,
        fetched=fetched,
    )


def _misses_templates(source: CampaignSource) -> bool:
    return any(
        isinstance(action.get("type"), str)
        and action["type"] in _MESSAGE_ACTION_TYPES
        and action.get("template_id") is not None
        and str(action["template_id"]) not in source.templates
        for action in source.actions
    )


def _with_fetched_templates(source: CampaignSource, app_actions: list[dict[str, Any]]) -> CampaignSource:
    """The source with a template for every message action whose App API action shares its id.

    Language variants share the default variant's id through `parent_action_id`, so the variant whose own id
    matches is the default-language message.
    """
    by_id = {str(app_action.get("id")): app_action for app_action in app_actions}
    templates = dict(source.templates)
    for action in source.actions:
        template_id = action.get("template_id")
        if template_id is None or str(template_id) in templates:
            continue
        app_action = by_id.get(str(action.get("id")))
        if app_action is not None:
            templates[str(template_id)] = _template_from_app_action(app_action)
    return CampaignSource(campaign=source.campaign, actions=source.actions, templates=templates)


def _template_from_app_action(app_action: dict[str, Any]) -> dict[str, Any]:
    """An App API action in the shape of a Journeys UI API template, which the translator reads."""
    headers = app_action.get("headers")
    if isinstance(headers, str):
        try:
            headers = json.loads(headers)
        except ValueError:
            headers = []
    return {
        "subject": app_action.get("subject"),
        "body": app_action.get("body"),
        "preheader_text": app_action.get("preheader_text"),
        "recipient": app_action.get("recipient"),
        "from": app_action.get("from"),
        "from_id": app_action.get("from_id"),
        "reply_to": app_action.get("reply_to"),
        "reply_to_id": app_action.get("reply_to_id"),
        "layout": app_action.get("layout"),
        "url": app_action.get("url"),
        "request_method": app_action.get("method"),
        "headers": headers if isinstance(headers, list) else [],
    }


def _stored_app_api_key(team_id: int) -> str | None:
    integration = IntegrationManager.customerio_app.token.find(team_id)
    key = (integration.sensitive_config or {}).get("app_api_key") if integration else None
    return str(key) if key else None


def _team_senders(team_id: int) -> dict[str, ImportSender]:
    senders: dict[str, ImportSender] = {}
    for integration in IntegrationManager.email.credentials.list(team_id):
        config = integration.config or {}
        address = str(config.get("email") or integration.integration_id or "").lower()
        if address:
            senders[address] = ImportSender(integration_id=integration.id, email=address, name=config.get("name") or "")
    return senders


def _topic_categories(team_id: int) -> dict[str, ImportCategory]:
    # The opt-out import keys each category `customerio_<topic identifier>`, and the identifier is `topic_<id>`.
    categories: dict[str, ImportCategory] = {}
    for category in list_categories(team_id):
        if category.deleted or not category.key.startswith("customerio_topic_"):
            continue
        topic_id = category.key.removeprefix("customerio_topic_")
        categories[topic_id] = ImportCategory(id=str(category.id), category_type=category.category_type)
    return categories


def _identity_addresses(identities: list[dict[str, Any]]) -> dict[str, str]:
    addresses: dict[str, str] = {}
    for identity in identities:
        if identity.get("id") is None:
            continue
        email = identity.get("email")
        if not email:
            continue
        name = identity.get("name")
        addresses[str(identity["id"])] = f"{name} <{email}>" if name else str(email)
    return addresses


def _segment_info(segments: list[dict[str, Any]]) -> dict[str, ImportSegment]:
    return {
        str(segment["id"]): ImportSegment(name=str(segment.get("name") or ""), type=str(segment.get("type") or ""))
        for segment in segments
        if isinstance(segment, dict) and segment.get("id") is not None
    }


def _snippet_values(snippets: list[dict[str, Any]]) -> dict[str, str]:
    return {
        str(snippet["name"]): str(snippet.get("value") or "")
        for snippet in snippets
        if isinstance(snippet, dict) and snippet.get("name")
    }
