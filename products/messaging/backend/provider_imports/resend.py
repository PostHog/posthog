"""Imports suppressions, topics and unsubscribes from Resend.

Resend has no read-only key, so the customer hands over one that can do anything in their account. The run keeps it
only until it ends, and a new import asks for it again. People never move: the contact steps read only who opted out.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import partial
from typing import Any

from django.utils.dateparse import parse_datetime

from posthog.helpers.email_utils import email_domain

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentials,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportPage,
    ImportProvider,
    ImportProviderUnavailable,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.resend_client import (
    ResendAPIError,
    ResendClient,
    ResendKeyCannotRead,
    ResendKeyRejected,
    ResendRateLimited,
)

# The key check runs on the request path, so it gets a short timeout and doesn't wait out a rate limit.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
MISSING_KEY_MESSAGE = "Enter your Resend API key. PostHog doesn't keep it between imports."
EXPIRED_KEY_MESSAGE = "PostHog deleted the Resend API key when this import ended. Start a new import."
INVALID_KEY_MESSAGE = (
    "Resend rejected this API key. Check that you copied all of it and that it's still active on your Resend "
    "API keys page."
)
SENDING_ONLY_KEY_MESSAGE = (
    "This Resend API key can only send email, so it can't read your data. Create a key with full access and try again."
)
RATE_LIMITED_MESSAGE = "Resend kept asking PostHog to slow down. Import again later."
TOPIC_KEY_PREFIX = "resend_"

_SUPPRESSION_ORIGINS: dict[str, tuple[SuppressionSource, str]] = {
    "bounce": (SuppressionSource.BOUNCE, "Imported from Resend (bounced)"),
    "complaint": (SuppressionSource.COMPLAINT, "Imported from Resend (spam complaint)"),
    "manual": (SuppressionSource.MANUAL, "Imported from Resend (added by your team)"),
}


class ResendImportProvider(ImportProvider):
    key = ImportProviderKey.RESEND.value
    label = ImportProviderKey.RESEND.label
    retains_credentials = False
    feature_flag = "workflows-resend-import"
    api_key_label = "Resend API key"
    api_key_help = (
        "Resend has no read-only keys, so this needs a key with full access. PostHog only reads from your account, "
        "deletes the key as soon as the import ends, and asks for it again next time. Delete the key in Resend "
        "afterward if you'd like."
    )
    api_key_url = "https://resend.com/api-keys"
    not_imported = (
        "Contacts don't become people in PostHog. API keys, webhooks, send history and stats stay in Resend, so "
        "rebuild what you need."
    )
    next_steps = ("Once nothing sends through Resend, delete the API key you created for this import.",)
    steps = (
        ImportStepSpec(
            key="topics",
            label="Topics",
            description="Creates a marketing message category for each Resend topic.",
            count_labels=(("created", "New categories"), ("already_present", "Already in PostHog, left as they are")),
        ),
        ImportStepSpec(
            key="suppressions",
            label="Suppression list",
            description="Adds every address on your Resend suppression list to your PostHog suppression list.",
            count_labels=(
                ("bounced", "Hard bounces, which block all email"),
                ("complained", "Spam complaints, which block marketing email only. Resend blocks all email to them."),
                ("manual", "Added by your team, which block marketing email only. Resend blocks all email to them."),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
            ),
        ),
        ImportStepSpec(
            key="opt_outs",
            label="Unsubscribed contacts",
            description=(
                "Opts contacts who unsubscribed in Resend out of all marketing email. PostHog reads their email "
                "address only and doesn't create people from your contacts."
            ),
            count_labels=(("opted_out", "Newly opted out"), ("subscribed", "Still subscribed, not imported")),
        ),
        ImportStepSpec(
            key="topic_opt_outs",
            label="Topic preferences",
            description=(
                "Opts contacts out of each topic they left in Resend. Resend only shares this one contact at a "
                "time, so PostHog reads about 7,000 contacts an hour. Large lists can take a day."
            ),
            count_labels=(("opted_out", "People with a new topic opt-out"), ("contacts", "Contacts checked")),
        ),
    )

    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        if not api_key:
            raise ImportCredentialsMissing(MISSING_KEY_MESSAGE)
        if not api_key.isascii():
            raise ImportCredentialsInvalid(INVALID_KEY_MESSAGE)
        client = ResendClient(api_key, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
        with _translated_errors():
            client.check_access()
        return ImportCredentials(api_key=api_key)

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_KEY_MESSAGE)
        client = ResendClient(context.api_key)
        with _translated_errors():
            match step:
                case "topics":
                    yield from _fetch_topics(client, context, checkpoint)
                case "suppressions":
                    yield from _fetch_suppressions(client, context, checkpoint)
                case "opt_outs":
                    yield from _fetch_opt_outs(client, context, checkpoint)
                case "topic_opt_outs":
                    yield from _fetch_topic_opt_outs(client, context, checkpoint)
                case _:
                    raise UnknownImportStep(f"Resend has no import step named {step}.")


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except ResendKeyCannotRead as e:
        raise ImportCredentialsInvalid(SENDING_ONLY_KEY_MESSAGE) from e
    except ResendKeyRejected as e:
        raise ImportCredentialsInvalid(INVALID_KEY_MESSAGE) from e
    except ResendRateLimited as e:
        raise ImportProviderUnavailable(RATE_LIMITED_MESSAGE) from e
    except ResendAPIError as e:
        raise ImportProviderUnavailable(str(e)) from e


def _after(checkpoint: StepCheckpoint | None) -> str | None:
    value = checkpoint.get("after") if checkpoint else None
    return str(value) if value else None


def _next_checkpoint(next_after: str | None) -> StepCheckpoint | None:
    return {"after": next_after} if next_after else None


def _normalized_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    return email if email_domain(email) and not email.startswith("@") and len(email) <= 512 else None


def _contact_email(value: Any) -> str | None:
    # Unlike a suppression row, an opt-out matches the address a send names exactly, so the case stays as Resend has it.
    return value.strip() if _normalized_email(value) else None


def _topic_key(topic_id: str) -> str:
    return f"{TOPIC_KEY_PREFIX}{topic_id}"[:64]


def _to_category(topic: dict[str, Any]) -> ImportedCategory | None:
    topic_id = topic.get("id")
    if not topic_id:
        return None
    return ImportedCategory(
        key=_topic_key(str(topic_id)),
        name=str(topic.get("name") or topic_id)[:128],
        description=str(topic.get("description") or ""),
    )


def _fetch_topics(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    for page in client.pages("/topics", _after(checkpoint)):
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_topics, context, page.data),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _save_topics(context: ImportContext, topics: list[dict[str, Any]]) -> SavedPage:
    categories = [category for category in map(_to_category, topics) if category]
    result = import_categories(context.team_id, categories, context.created_by_id)
    return SavedPage(
        imported=result.created,
        counts={"created": result.created, "already_present": result.already_present},
        warnings=tuple(
            f"{topic.get('name') or topic.get('id')}: Resend only sends this topic to people who opted in. PostHog "
            "sends a category to everyone who hasn't opted out, so check who you send it to."
            for topic in topics
            if topic.get("default_subscription") == "opt_out"
        ),
    )


def _fetch_suppressions(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    for page in client.pages("/suppressions", _after(checkpoint)):
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_suppressions, context, page.data),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _save_suppressions(context: ImportContext, entries: list[dict[str, Any]]) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for entry in entries:
        email = _normalized_email(entry.get("email"))
        origin = _SUPPRESSION_ORIGINS.get(str(entry.get("origin")))
        if email is None or origin is None:
            invalid += 1
            continue
        source, reason = origin
        # A hard bounce outranks another entry for the same address, because only a bounce blocks transactional email.
        if email in imported and imported[email].source == SuppressionSource.BOUNCE:
            continue
        imported[email] = ImportedSuppression(
            identifier=email, source=source, reason=reason, suppressed_at=_timestamp(entry.get("created_at"))
        )
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
    return SavedPage(
        imported=result.total_added,
        counts={
            "bounced": result.added.get(SuppressionSource.BOUNCE, 0),
            "complained": result.added.get(SuppressionSource.COMPLAINT, 0),
            "manual": result.added.get(SuppressionSource.MANUAL, 0),
            "already_present": result.already_present,
            "invalid": invalid,
        },
    )


def _timestamp(value: Any) -> datetime | None:
    try:
        return parse_datetime(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _fetch_opt_outs(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    for page in client.pages("/contacts", _after(checkpoint)):
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_opt_outs, context, page.data),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _save_opt_outs(context: ImportContext, contacts: list[dict[str, Any]]) -> SavedPage:
    unsubscribed = {
        email: [ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
        for contact in contacts
        if contact.get("unsubscribed") is True and (email := _contact_email(contact.get("email")))
    }
    changed = import_opt_outs(context.team_id, unsubscribed, context.created_by_id)
    return SavedPage(imported=changed, counts={"opted_out": changed, "subscribed": len(contacts) - len(unsubscribed)})


def _fetch_topic_opt_outs(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    # Each contact costs one request, so an account without topics shouldn't read its whole contact list.
    if not next(client.pages("/topics")).data:
        yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    for page in client.pages("/contacts", _after(checkpoint)):
        topics_by_email: dict[str, list[dict[str, Any]]] = {}
        for contact in page.data:
            email = _contact_email(contact.get("email"))
            contact_id = contact.get("id")
            # Everyone unsubscribed is already out of every topic through the global opt-out.
            if email and contact_id and contact.get("unsubscribed") is not True:
                topics_by_email[email] = [
                    topic
                    for topics in client.pages(f"/contacts/{contact_id}/topics")
                    for topic in topics.data
                    if topic.get("subscription") == "opt_out"
                ]
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_topic_opt_outs, context, topics_by_email, len(page.data)),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _save_topic_opt_outs(
    context: ImportContext, topics_by_email: dict[str, list[dict[str, Any]]], contacts: int
) -> SavedPage:
    categories = {
        category.key: category
        for topics in topics_by_email.values()
        for category in map(_to_category, topics)
        if category
    }
    ids_by_key = import_categories(context.team_id, categories.values(), context.created_by_id).ids_by_key
    opt_outs = {
        email: [ids_by_key[key] for topic in topics if (key := _topic_key(str(topic.get("id")))) in ids_by_key]
        for email, topics in topics_by_email.items()
    }
    changed = import_opt_outs(context.team_id, opt_outs, context.created_by_id)
    return SavedPage(imported=changed, counts={"opted_out": changed, "contacts": contacts})
