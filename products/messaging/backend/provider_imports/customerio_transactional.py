"""Imports Customer.io transactional messages as PostHog templates made transactional, one per language.

Customer.io's App API returns each message's content per language (`GET /v1/transactional/{id}/contents`). The
content goes through the same conversion as automation emails, except that `trigger` reads the send's
`message_data`. A template is only kept once it's transactional, so an import never leaves one that can't send.
"""

import re
import time
from collections import Counter
from collections.abc import Iterator
from functools import partial
from typing import Any

from django.db import transaction

from posthog.integrations import IntegrationManager

from products.messaging.backend.facade.contracts import TransactionalEmailError
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.transactional_email_key import lock_team_keys
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportItem,
    ImportPage,
    ImportProviderUnavailable,
    ImportStepBlocked,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
)
from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOClient
from products.messaging.backend.services.imported_data import code_email_keys
from products.messaging.backend.services.message_templates import (
    TRANSACTIONAL_EMAIL_API_FLAG,
    create_template,
    with_editor_design,
)
from products.workflows.backend.facade.api import pick_default_email_sender
from products.workflows.backend.facade.contracts import ImportOptions, SnippetRoom, TranslatedTransactionalEmail
from products.workflows.backend.facade.workflow_imports import (
    transactional_import_options,
    translate_transactional_email,
)

IMPORT_TAG = "imported-from-customerio"
KEY_PREFIX = "customerio-transactional-"
MESSAGES_PER_PAGE = 20
_KEY_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")
# Reading the sender identities and snippets with the stored key, once per step.
LOOKUP_SECONDS = 60
CONTENT_READ_INTERVAL_SECONDS = 0.125
CONTENT_READ_ATTEMPTS = 3
RATE_LIMIT_BACKOFF_SECONDS = 2
NO_SENDER_MESSAGE = (
    "PostHog has no verified email sender, so it imported no transactional messages. Verify a sending domain, then "
    "run the import again."
)

TRANSACTIONAL_STEP = ImportStepSpec(
    key="transactional",
    label="Transactional messages",
    description=(
        "Copies each transactional message into a PostHog template and makes it transactional, so your app can send "
        "it through PostHog. Each translation gets its own template. Needs a verified email sender in PostHog. "
        "Messages you already imported stay as they are."
    ),
    count_labels=(
        ("created", "New transactional templates"),
        ("needs_review", "New transactional templates to review"),
        ("already_present", "Already in PostHog, left as they are"),
        ("empty", "Messages with no content in Customer.io"),
        ("failed", "Messages that couldn't be made transactional"),
    ),
    feature_flag=TRANSACTIONAL_EMAIL_API_FLAG,
    hidden_note="Transactional messages stay in Customer.io until transactional email is on for this project.",
    next_steps=(
        "Change each transactional send in your app's code from Customer.io to PostHog's send API. Each imported "
        "transactional message above says what to send. The recipient and message data stay the same, and profile "
        "attributes the email used now come with the message data.",
    ),
)


def fetch_transactional(
    client: CustomerIOClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    if not _verified_senders(context.team_id):
        raise ImportStepBlocked(NO_SENDER_MESSAGE)
    messages = sorted(client.get_transactional_messages(), key=lambda message: int(message.get("id") or 0))
    options = transactional_import_options(context.team_id, deadline=time.monotonic() + LOOKUP_SECONDS)
    if options is None:
        raise ImportProviderUnavailable(
            "Customer.io didn't return its sender identities and snippets. Run the import again in a few minutes."
        )
    start = int(checkpoint.get("offset", 0)) if checkpoint else 0
    if start >= len(messages):
        yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    for offset in range(start, len(messages), MESSAGES_PER_PAGE):
        page = messages[offset : offset + MESSAGES_PER_PAGE]
        with_contents = [(message, _read_contents(client, message["id"])) for message in page]
        next_offset = offset + MESSAGES_PER_PAGE
        yield ImportPage(
            processed=len(page),
            save=partial(_save_messages, context, with_contents, options),
            checkpoint={"offset": next_offset} if next_offset < len(messages) else None,
        )


def _save_messages(
    context: ImportContext,
    with_contents: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    options: ImportOptions,
) -> SavedPage:
    fallback_sender = pick_default_email_sender(context.team_id, _verified_senders(context.team_id))
    keys = [key for message, contents in with_contents for key, _ in _keyed(message, contents)]
    rows = list(
        MessageTemplate.objects.filter(team_id=context.team_id, key__in=keys).values_list(
            "key", "id", "deleted", "transactional_hog_flow_id"
        )
    )
    existing = {key: (template_id, flow_id is not None) for key, template_id, deleted, flow_id in rows if not deleted}
    # Held until the page commits, so a send can't add a code email key between this check and the creates below.
    lock_team_keys(context.team_id)
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = {row[0] for row in rows} | code_email_keys(context.team_id, keys)

    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    room = SnippetRoom()
    for message, contents in with_contents:
        keyed = _keyed(message, contents)
        if not keyed:
            counts["empty"] += 1
            items.append(
                ImportItem(
                    label=_name(message),
                    status="listed",
                    notes=("This message has no subject or body in Customer.io, so there was nothing to import.",),
                )
            )
            continue
        languages = [_language(content) for _, content in keyed if _language(content)]
        for key, content in keyed:
            name = _name(message, _language(content))
            if key in taken:
                counts["already_present"] += 1
                items.append(ImportItem(label=name, status="skipped", notes=_skipped_notes(key, existing.get(key))))
                continue
            # Two language codes can turn into one key, such as `pt.BR` and `pt-BR`.
            taken.add(key)
            translated = translate_transactional_email({**content, "name": name}, options, room)
            item, count_key = _import_one(context, message, content, key, name, translated, fallback_sender, languages)
            items.append(item)
            counts[count_key] += 1
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _import_one(
    context: ImportContext,
    message: dict[str, Any],
    content: dict[str, Any],
    key: str,
    name: str,
    translated: TranslatedTransactionalEmail,
    fallback_sender: int | None,
    languages: list[str],
) -> tuple[ImportItem, str]:
    sender_id = translated.from_integration_id or fallback_sender
    if sender_id is None:
        return ImportItem(
            label=name,
            status="failed",
            notes=(
                "PostHog couldn't tell which sender to send this from, because none matches its Customer.io sender and "
                "the project has several verified senders but no default. Nothing was imported. Choose a default "
                "sender, then import again.",
            ),
        ), "failed"
    notes = (*translated.notes, *_message_notes(message, content, languages))
    email: dict[str, Any] = {
        "subject": translated.subject,
        "preheader": translated.preheader,
        "html": translated.html,
        "from": {"integrationId": sender_id, "email": "", "name": translated.from_name},
        "replyTo": translated.reply_to,
    }
    if translated.text:
        email["text"] = translated.text
    # The transactional email service imports the import runner through its tasks.
    from products.messaging.backend.services.transactional_email import make_transactional

    try:
        # A savepoint, so a template that can't be made transactional leaves nothing behind.
        with transaction.atomic():
            template = create_template(
                context.team_id,
                context.created_by_id,
                {
                    "name": name,
                    "key": key,
                    "description": " ".join(
                        (f"Imported from Customer.io transactional message {message['id']}.", *notes)
                    ),
                    "type": "email",
                    "content": {"templating": "liquid", "email": with_editor_design(email)},
                    "sensitive": bool(message.get("hide_message_body")),
                    "click_tracking_enabled": False if message.get("link_tracking") is False else None,
                    "tags": [IMPORT_TAG],
                },
            )
            make_transactional(
                context.team_id, template.id, user_id=context.created_by_id, from_integration_id=sender_id
            )
    except TransactionalEmailError as e:
        return ImportItem(label=name, status="failed", notes=(f"{e} Nothing was imported for it.", *notes)), "failed"
    item = ImportItem(
        label=name,
        status="created",
        url=f"/workflows/library/templates/{template.id}",
        notes=(*notes, send_instructions(message, template.id, translated)),
    )
    return item, "needs_review" if notes else "created"


def send_instructions(message: dict[str, Any], template_id: Any, translated: TranslatedTransactionalEmail) -> str:
    """How to change the app's Customer.io send of this message to a PostHog send."""
    parts = [
        "Your app's code has to change to send this from PostHog. Instead of Customer.io's POST /v1/send/email with "
        f'"transactional_message_id": {message["id"]}, call POST /api/messaging/send/email/ with '
        f'"template_id": "{template_id}" and your project secret API key. Keep "to" as it is, and pass the id, email '
        'or cio_id from "identifiers" as "distinct_id".'
    ]
    if translated.variables:
        parts.append(f'"message_data" stays the same. This email reads {_listed(translated.variables)} from it.')
    else:
        parts.append('This email reads nothing from "message_data".')
    if translated.customer_attributes:
        example = ", ".join(f'"{name}": ...' for name in translated.customer_attributes)
        parts.append(
            f"Customer.io read {_listed(translated.customer_attributes)} from the person's profile. PostHog templates "
            f'can\'t read people, so send them in "message_data" too, as "customer": {{{example}}}.'
        )
    return " ".join(parts)


def _listed(names: tuple[str, ...]) -> str:
    return ", ".join(names[:-1]) + (" and " if len(names) > 1 else "") + names[-1]


def _skipped_notes(key: str, existing: tuple[Any, bool] | None) -> tuple[str, ...]:
    if existing is None:
        return (
            f"A template with the key {key} was deleted in PostHog, or another template or a code email uses it, so "
            "this one wasn't imported.",
        )
    template_id, transactional = existing
    if not transactional:
        return (
            f"A template with the key {key} is already in PostHog, so it stays as it is. It isn't transactional "
            "anymore, so make it transactional again on its API tab before your app sends it.",
        )
    return (
        f"A template with the key {key} is already in PostHog, so it stays as it is. Your app sends it with "
        f'POST /api/messaging/send/email/ and "template_id": "{template_id}".',
    )


def _message_notes(message: dict[str, Any], content: dict[str, Any], languages: list[str]) -> tuple[str, ...]:
    notes: list[str] = []
    if languages and not _language(content):
        keys = ", ".join(dict.fromkeys(_key(message, language) for language in languages))
        notes.append(
            f"Customer.io also sends this message in {', '.join(languages)}, which picks the language from the "
            f"person's profile. Each language has its own template ({keys}), so your app picks the template instead."
        )
    if message.get("send_to_unsubscribed") is False:
        notes.append(
            "Customer.io doesn't send this message to people who unsubscribed. PostHog transactional email ignores "
            "opt-outs, so check that your app only sends it to people who want it."
        )
    if message.get("queue_drafts"):
        notes.append("Customer.io holds each send as a draft for you to review. PostHog sends it right away.")
    if message.get("open_tracking") is False:
        notes.append("Customer.io doesn't track opens of this message. PostHog does.")
    return tuple(notes)


def _keyed(message: dict[str, Any], contents: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """Each language that has content, default first, with the key its template gets."""
    with_content = [
        content
        for content in contents
        if (content.get("body") or "").strip()
        or (content.get("body_plain") or "").strip()
        or (content.get("subject") or "").strip()
    ]
    with_content.sort(key=lambda content: (bool(_language(content)), _language(content)))
    return [(_key(message, _language(content)), content) for content in with_content]


def _key(message: dict[str, Any], language: str) -> str:
    suffix = f"-{_KEY_UNSAFE.sub('-', language)}" if language else ""
    return f"{KEY_PREFIX}{message['id']}{suffix}"


def _language(content: dict[str, Any]) -> str:
    return str(content.get("language") or "")


def _name(message: dict[str, Any], language: str = "") -> str:
    name = str(message.get("name") or f"Customer.io transactional message {message.get('id')}")
    return (f"{name} ({language})" if language else name)[:400]


def _read_contents(client: CustomerIOClient, transactional_id: Any) -> list[dict[str, Any]]:
    """One message's contents, paced under Customer.io's limit of 10 requests a second, and retried on a 429."""
    for attempt in range(CONTENT_READ_ATTEMPTS):
        time.sleep(CONTENT_READ_INTERVAL_SECONDS)
        try:
            return client.get_transactional_contents(transactional_id)
        except CustomerIOAPIError as e:
            if e.status_code != 429 or attempt == CONTENT_READ_ATTEMPTS - 1:
                raise
            time.sleep(RATE_LIMIT_BACKOFF_SECONDS)
    return []


def _verified_senders(team_id: int) -> frozenset[int]:
    return frozenset(
        sender.id
        for sender in IntegrationManager.email.credentials.list(team_id)
        if (sender.config or {}).get("verified")
    )
