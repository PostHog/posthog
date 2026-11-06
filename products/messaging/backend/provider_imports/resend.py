"""Imports suppressions, topics and unsubscribes from Resend.

Resend has no read-only key, so the customer hands over one that can do anything in their account. The run keeps it
only until it ends, and a new import asks for it again. People never move: the contact steps read only who opted out.
"""

import re
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from email.utils import parseaddr
from functools import partial
from typing import Any

from django.utils.dateparse import parse_datetime

from posthog.helpers.email_utils import email_domain
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_preferences import (
    ALL_MESSAGE_PREFERENCE_CATEGORY_ID,
    MessageRecipientPreference,
    PreferenceStatus,
)
from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentials,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportItem,
    ImportPage,
    ImportProvider,
    ImportProviderUnavailable,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.provider_imports.resend_templates import ConvertedTemplate, convert_template
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.message_templates import create_template
from products.messaging.backend.services.resend_client import (
    ResendAPIError,
    ResendClient,
    ResendKeyCannotRead,
    ResendKeyRejected,
    ResendRateLimited,
)
from products.workflows.backend.facade.contracts import ImportedEmail
from products.workflows.backend.facade.workflow_imports import import_resend_automation

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
TEMPLATE_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,400}")
IMPORT_TAG = "imported-from-resend"
# The label PostHog uses for a sender's MAIL FROM subdomain unless the person picks another.
MAIL_FROM_DEFAULT = "feedback"

_SUPPRESSION_ORIGINS: dict[str, tuple[SuppressionSource, str]] = {
    "bounce": (SuppressionSource.BOUNCE, "Imported from Resend (bounced)"),
    "complaint": (SuppressionSource.COMPLAINT, "Imported from Resend (spam complaint)"),
    "manual": (SuppressionSource.MANUAL, "Imported from Resend (added by your team)"),
}


class ResendImportProvider(ImportProvider):
    key = ImportProviderKey.RESEND.value
    label = ImportProviderKey.RESEND.label
    retains_credentials = False
    resumes_after_failure = True
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
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so "
        "this needs new records. Leave your Resend records in place, because both tools can sign mail for one domain "
        "while you move.",
        "Open each template with notes and fix what they mention, then send yourself a test.",
        "Make a template transactional and change your app to send it through PostHog. Start with a low-risk email "
        "and move the rest one at a time.",
        "If you send a lot of email, move it over several days. Mailbox providers slow down mail from a sender "
        "whose volume jumps.",
        "Once nothing sends through Resend, remove its DNS records and delete the API key you created for this import.",
    )
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
        ImportStepSpec(
            key="templates",
            label="Templates",
            description=(
                "Copies each template into your PostHog library with its alias as the key, and notes anything to "
                "review. Templates you already have here stay as they are."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
            ),
        ),
        ImportStepSpec(
            key="automations",
            label="Automations",
            description=(
                "Creates a draft workflow from each Resend automation, with notes on what to set before you enable "
                "it. Drafts never send on their own."
            ),
            count_labels=(
                ("created", "New draft workflows"),
                ("already_present", "Imported before, left as they are"),
                ("failed", "Couldn't be imported"),
            ),
        ),
        ImportStepSpec(
            key="domains",
            label="Sending domains",
            description=(
                "Lists your Resend domains and which of them can already send from PostHog. Domains can't be copied, "
                "because PostHog signs mail with its own keys, so each one needs new DNS records."
            ),
            count_labels=(("ready", "Ready to send from PostHog"), ("needs_setup", "Need new DNS records")),
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
                case "templates":
                    yield from _fetch_templates(client, context, checkpoint)
                case "automations":
                    yield from _fetch_automations(client, context, checkpoint)
                case "domains":
                    yield from _fetch_domains(client, context, checkpoint)
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
        opted_out_of_all = _emails_opted_out_of_all(context.team_id, page.data)
        topics_by_email: dict[str, list[dict[str, Any]]] = {}
        for contact in page.data:
            email = _contact_email(contact.get("email"))
            contact_id = contact.get("id")
            if email and contact_id and email not in opted_out_of_all:
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


def _emails_opted_out_of_all(team_id: int, contacts: list[dict[str, Any]]) -> set[str]:
    """Who already left every topic, so their topic choices aren't worth a request. Reads what PostHog stored, because
    the step that stores it may not have run."""
    unsubscribed = [
        email
        for contact in contacts
        if contact.get("unsubscribed") is True and (email := _contact_email(contact.get("email")))
    ]
    return {
        identifier
        for identifier, preferences in MessageRecipientPreference.objects.filter(
            team_id=team_id, identifier__in=unsubscribed
        ).values_list("identifier", "preferences")
        if (preferences or {}).get(ALL_MESSAGE_PREFERENCE_CATEGORY_ID) == PreferenceStatus.OPTED_OUT.value
    }


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


def _fetch_templates(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    for page in client.pages("/templates", _after(checkpoint)):
        # The list has no content, so each template costs one more request.
        templates = [client.get(f"/templates/{template['id']}") for template in page.data if template.get("id")]
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_templates, context, templates),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _template_key(template: dict[str, Any]) -> str:
    alias = str(template.get("alias") or "").strip()
    if alias and TEMPLATE_KEY_PATTERN.fullmatch(alias):
        return alias[:400]
    return f"resend-{template.get('id')}"[:400]


def _save_templates(context: ImportContext, templates: list[dict[str, Any]]) -> SavedPage:
    senders = _senders(context.team_id)
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = set(
        MessageTemplate.objects.filter(
            team_id=context.team_id, key__in=[_template_key(t) for t in templates]
        ).values_list("key", flat=True)
    )
    items: list[ImportItem] = []
    counts: Counter[str] = Counter()
    for template in templates:
        key = _template_key(template)
        name = str(template.get("name") or key)[:400]
        if key in taken:
            counts["already_present"] += 1
            items.append(ImportItem(label=name, status="skipped", notes=(f"A template with the key {key} exists.",)))
            continue
        taken.add(key)
        converted = convert_template(template)
        email, sender_notes = _email_content(template, converted, senders)
        notes = (*converted.notes, *converted.send_notes, *sender_notes)
        created = create_template(
            context.team_id,
            context.created_by_id,
            {
                "name": name,
                "key": key,
                "description": " ".join(("Imported from Resend.", *notes)),
                "type": "email",
                "content": {"templating": "liquid", "email": email},
                "tags": [IMPORT_TAG],
            },
        )
        counts["needs_review" if notes else "created"] += 1
        items.append(
            ImportItem(label=name, status="created", url=f"/workflows/library/templates/{created.id}", notes=notes)
        )
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _senders(team_id: int) -> dict[str, IntegrationRecord]:
    return {
        str(sender.config.get("email", "")).lower(): sender
        for sender in IntegrationManager.email.credentials.list(team_id)
    }


def _email_content(
    template: dict[str, Any], converted: ConvertedTemplate, senders: Mapping[str, IntegrationRecord]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    email: dict[str, Any] = {"subject": converted.subject, "html": converted.html}
    if converted.text:
        email["text"] = converted.text
    reply_to = template.get("reply_to")
    if reply_to:
        email["replyTo"] = ", ".join(reply_to) if isinstance(reply_to, list) else str(reply_to)
    display_name, address = parseaddr(str(template.get("from") or ""))
    if not address:
        return email, ("Resend has no sender for this template. Choose one before you send it.",)
    sender = senders.get(address.lower())
    if sender is None:
        return email, (f"{address} isn't a PostHog sender yet. Add it, then choose it on this template.",)
    email["from"] = {
        "integrationId": sender.id,
        "email": address,
        "name": display_name or str(sender.config.get("name") or ""),
    }
    if not sender.config.get("verified"):
        return email, (f"{address} isn't verified in PostHog yet, so this template can't send until it is.",)
    return email, ()


def _fetch_automations(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    # Automations often share templates, and each read costs one request against the customer's rate limit.
    templates: dict[str, dict[str, Any] | None] = {}
    for page in client.pages("/automations", _after(checkpoint)):
        automations = [client.get(f"/automations/{item['id']}") for item in page.data if item.get("id")]
        references = {reference for automation in automations for reference in _template_references(automation)}
        for reference in references:
            if reference not in templates:
                templates[reference] = _read_template(client, reference)
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_automations, context, automations, {ref: templates[ref] for ref in references}),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _template_references(automation: dict[str, Any]) -> set[str]:
    references = set()
    for step in automation.get("steps") or []:
        if isinstance(step, dict) and step.get("type") == "send_email":
            reference = ((step.get("config") or {}).get("template") or {}).get("id")
            if reference:
                references.add(str(reference))
    return references


def _read_template(client: ResendClient, reference: str) -> dict[str, Any] | None:
    try:
        return client.get(f"/templates/{reference}")
    except ResendAPIError as e:
        # A step can name a deleted template. Its draft gets a note, and the rest of the import carries on.
        if e.status_code == 404:
            return None
        raise


def _save_automations(
    context: ImportContext, automations: list[dict[str, Any]], templates: dict[str, dict[str, Any] | None]
) -> SavedPage:
    senders = _senders(context.team_id)
    emails = {
        reference: _imported_email(template, senders) if template else None for reference, template in templates.items()
    }
    items: list[ImportItem] = []
    counts: Counter[str] = Counter()
    for automation in automations:
        result = import_resend_automation(context.team_id, context.created_by_id, automation, emails)
        counts[{"created": "created", "skipped": "already_present"}.get(result.status, "failed")] += 1
        items.append(
            ImportItem(
                label=str(automation.get("name") or automation.get("id")),
                status="created"
                if result.status == "created"
                else "skipped"
                if result.status == "skipped"
                else "failed",
                url=f"/workflows/{result.workflow_id}/workflow" if result.workflow_id else None,
                notes=result.notes,
            )
        )
    return SavedPage(imported=counts["created"], counts=dict(counts), items=tuple(items))


def _imported_email(template: dict[str, Any], senders: Mapping[str, IntegrationRecord]) -> ImportedEmail:
    converted = convert_template(template)
    email, sender_notes = _email_content(template, converted, senders)
    display_name, address = parseaddr(str(template.get("from") or ""))
    sender = email.get("from") or {}
    return ImportedEmail(
        subject=converted.subject,
        html=converted.html,
        text=converted.text,
        from_email=address,
        from_name=display_name,
        sender_integration_id=sender.get("integrationId"),
        reply_to=email.get("replyTo", ""),
        notes=(*converted.notes, *sender_notes),
    )


def _fetch_domains(
    client: ResendClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    for page in client.pages("/domains", _after(checkpoint)):
        details = [client.get(f"/domains/{domain['id']}") for domain in page.data if domain.get("id")]
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_domains, context, details),
            checkpoint=_next_checkpoint(page.next_after),
        )


def _save_domains(context: ImportContext, domains: list[dict[str, Any]]) -> SavedPage:
    senders_by_domain: dict[str, list[IntegrationRecord]] = {}
    for sender in IntegrationManager.email.credentials.list(context.team_id):
        senders_by_domain.setdefault(str(sender.config.get("domain", "")).lower(), []).append(sender)
    items: list[ImportItem] = []
    counts: Counter[str] = Counter()
    for domain in domains:
        name = str(domain.get("name") or "")
        senders = senders_by_domain.get(name.lower(), [])
        ready = any(sender.config.get("verified") for sender in senders)
        notes: list[str] = []
        if not ready:
            notes.append(
                "Waiting for DNS. Check the records on this domain's page."
                if senders
                else "Add this domain in PostHog to get its DNS records."
            )
        if _uses_mail_from_label(domain, MAIL_FROM_DEFAULT):
            notes.append(
                f"Resend already uses the {MAIL_FROM_DEFAULT} subdomain here. Choose a different MAIL FROM subdomain "
                "in PostHog, or both tools will share one MX record and one of them will break."
            )
        counts["ready" if ready else "needs_setup"] += 1
        items.append(
            ImportItem(
                label=name,
                status="listed",
                url=f"/workflows/channels/email/{senders[0].id}" if senders else "/workflows/channels",
                notes=tuple(notes),
            )
        )
    return SavedPage(imported=0, counts=dict(counts), items=tuple(items))


def _uses_mail_from_label(domain: dict[str, Any], label: str) -> bool:
    return any(
        isinstance(record, dict)
        and str(record.get("type", "")).upper() == "MX"
        and str(record.get("name", "")).split(".")[0].lower() == label
        for record in domain.get("records") or []
    )
