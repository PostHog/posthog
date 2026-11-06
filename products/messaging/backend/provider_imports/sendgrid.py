"""Imports suppressions, unsubscribe groups and templates from SendGrid, and lists what can't move.

SendGrid is the one provider here with read-only scopes, so the customer can hand over a narrow key. The run still only
keeps it until it ends. SendGrid documents only stats for its automations, so they stay behind. Contacts don't become
people. A send to any address reads the blocking rules this import fills, so PostHog doesn't need them.
"""

import json
import hashlib
from collections import Counter
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Any

from django.utils import timezone

from posthog.helpers.email_utils import email_domain
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
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
from products.messaging.backend.provider_imports.sendgrid_templates import ConvertedSendGridTemplate, convert_version
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.message_templates import create_template
from products.messaging.backend.services.sendgrid_client import (
    TEMPLATE_PAGE_SIZE,
    SendGridAPIError,
    SendGridClient,
    SendGridKeyRejected,
    SendGridRateLimited,
    SendGridScopeMissing,
    connect,
)

CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
MISSING_KEY_MESSAGE = "Enter your SendGrid API key. PostHog doesn't keep it between imports."
EXPIRED_KEY_MESSAGE = "PostHog deleted the SendGrid API key when this import ended. Start a new import."
INVALID_KEY_MESSAGE = (
    "SendGrid rejected this API key. Check that you copied all of it and that it's still active on your SendGrid "
    "API keys page."
)
RATE_LIMITED_MESSAGE = "SendGrid kept asking PostHog to slow down. Import again later."
GROUP_KEY_PREFIX = "sendgrid_"
IMPORT_TAG = "imported-from-sendgrid"
MAIL_FROM_DEFAULT = "feedback"
OPT_OUT_PAGE_SIZE = 500
MAX_SAMPLE_DATA_LENGTH = 2000

# A step's scopes per https://www.twilio.com/docs/sendgrid/api-reference/api-key-permissions. A tuple means any one of
# them is enough. Designs and verified senders are missing because SendGrid names no scope for them, so a key that can't
# read those fails on the step itself with a message naming it.
STEP_SCOPES: dict[str, tuple[tuple[str, ...], ...]] = {
    "suppression_groups": (("asm.groups.read",),),
    "suppressions": (
        ("suppression.bounces.read", "suppression.read"),
        ("suppression.invalid_emails.read", "suppression.read"),
        ("suppression.spam_reports.read", "suppression.read"),
    ),
    "global_unsubscribes": (("suppression.unsubscribes.read", "suppression.read"),),
    "group_unsubscribes": (("asm.groups.read",),),
    "templates": (("templates.read",), ("templates.versions.read",)),
    "single_sends": (("marketing.read",),),
    "lists": (("marketing.read",),),
    "domains": (("whitelabel.read",),),
}
SUPPRESSION_LISTS: tuple[tuple[str, str, SuppressionSource, str], ...] = (
    # Bounces go first because the first row for an address stays, and only a bounce blocks transactional email.
    ("bounces", "/v3/suppression/bounces", SuppressionSource.BOUNCE, "Imported from SendGrid (bounced)"),
    ("invalid", "/v3/suppression/invalid_emails", SuppressionSource.BOUNCE, "Imported from SendGrid (invalid address)"),
    ("spam", "/v3/suppression/spam_reports", SuppressionSource.COMPLAINT, "Imported from SendGrid (spam report)"),
)


class SendGridImportProvider(ImportProvider):
    key = ImportProviderKey.SENDGRID.value
    label = ImportProviderKey.SENDGRID.label
    retains_credentials = False
    resumes_after_failure = True
    feature_flag = "workflows-sendgrid-import"
    api_key_label = "SendGrid API key"
    api_key_help = (
        "Create a key with restricted access and read access to what you're importing. Each step lists what it needs. "
        "PostHog only reads from your account, deletes the key as soon as the import ends, and asks for it again next "
        "time. A key belongs to one account, so import each subuser with its own key."
    )
    api_key_url = "https://app.sendgrid.com/settings/api_keys"
    not_imported = (
        "SendGrid's API only shares stats for automations, so rebuild them as workflows. Blocks stay behind because "
        "SendGrid doesn't keep suppressing those addresses either. Contacts don't become people. Webhooks, API keys, "
        "stats, send history and inactive template versions stay in SendGrid."
    )
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so this "
        "needs new records. Leave your SendGrid records in place, because both tools can sign mail for one domain "
        "while you move.",
        "Open each template with notes and fix what they mention, then send yourself a test.",
        "Make a template transactional and change your app to send it through PostHog. Its key is the SendGrid "
        "template ID, and your data goes in as variables. Start with a low-risk email and move the rest one at a time.",
        "Rebuild your SendGrid automations as workflows, using the imported templates, and turn each one off in "
        "SendGrid when its workflow goes live.",
        "If you send a lot of email, move it over several days. Mailbox providers slow down mail from a sender "
        "whose volume jumps.",
        "Once nothing sends through SendGrid, remove its DNS records and delete the API key you created for this "
        "import.",
    )
    steps = (
        ImportStepSpec(
            key="suppression_groups",
            label="Unsubscribe groups",
            description="Creates a marketing message category for each unsubscribe group. Needs asm.groups.read.",
            count_labels=(("created", "New categories"), ("already_present", "Already in PostHog, left as they are")),
        ),
        ImportStepSpec(
            key="suppressions",
            label="Bounces, invalid addresses and spam reports",
            description=(
                "Adds these to your PostHog suppression list. Needs suppression.bounces.read, "
                "suppression.invalid_emails.read and suppression.spam_reports.read."
            ),
            count_labels=(
                ("bounced", "Bounces, which block all email"),
                ("invalid_addresses", "Invalid addresses, which block all email"),
                ("complained", "Spam reports, which block marketing email only. SendGrid blocks all email to them."),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
            ),
        ),
        ImportStepSpec(
            key="global_unsubscribes",
            label="Global unsubscribes",
            description=(
                "Opts these people out of all marketing email. SendGrid also stops transactional email to them, and "
                "PostHog doesn't. Needs suppression.unsubscribes.read."
            ),
            count_labels=(("opted_out", "Newly opted out"), ("invalid", "Skipped because the address isn't valid")),
        ),
        ImportStepSpec(
            key="group_unsubscribes",
            label="Group unsubscribes",
            description="Opts people out of the category for each group they left. Needs asm.groups.read.",
            count_labels=(("opted_out", "People with a new opt-out"), ("invalid", "Skipped, address isn't valid")),
        ),
        ImportStepSpec(
            key="templates",
            label="Dynamic and legacy templates",
            description=(
                "Copies each template's active version into your PostHog library, with the SendGrid template ID as its "
                "key, and notes anything to review. Templates you already have here stay as they are. Needs "
                "templates.read and templates.versions.read."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
                ("no_version", "Skipped because they have no versions"),
            ),
        ),
        ImportStepSpec(
            key="designs",
            label="Design Library",
            description="Copies each design you saved into your PostHog library as a template.",
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
            ),
        ),
        ImportStepSpec(
            key="single_sends",
            label="Single Sends",
            description=(
                "Copies the content of each Single Send into your PostHog library as a template. Nothing sends, and "
                "anything scheduled in SendGrid stays scheduled there. Needs marketing.read, which SendGrid also lets "
                "write to your marketing data."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
            ),
        ),
        ImportStepSpec(
            key="lists",
            label="Contact lists",
            description=(
                "Lists your contact lists and how many people are on them, so you know what to rebuild. Contacts don't "
                "become people in PostHog. Needs marketing.read, which SendGrid also lets write to your marketing data."
            ),
            count_labels=(("lists", "Lists"), ("contacts", "Contacts in your account")),
        ),
        ImportStepSpec(
            key="senders",
            label="Verified senders",
            description="Lists your verified senders and which of them can already send from PostHog.",
            count_labels=(("ready", "Ready to send from PostHog"), ("needs_setup", "Need adding in PostHog")),
        ),
        ImportStepSpec(
            key="domains",
            label="Authenticated domains",
            description=(
                "Lists your authenticated domains and which of them can already send from PostHog. Domains can't be "
                "copied, because PostHog signs mail with its own keys. Needs whitelabel.read."
            ),
            count_labels=(("ready", "Ready to send from PostHog"), ("needs_setup", "Need new DNS records")),
        ),
    )

    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        if not api_key:
            raise ImportCredentialsMissing(MISSING_KEY_MESSAGE)
        if not api_key.isascii():
            raise ImportCredentialsInvalid(INVALID_KEY_MESSAGE)
        with _translated_errors():
            connect(api_key, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
        return ImportCredentials(api_key=api_key)

    def check_step_access(self, team_id: int, credentials: ImportCredentials, steps: list[str]) -> None:
        with _translated_errors():
            _, scopes = connect(credentials.api_key, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
        missing = missing_scopes(scopes, steps)
        if missing:
            raise ImportCredentialsInvalid(
                f"This SendGrid API key is missing {', '.join(missing)}. Add these in SendGrid, or turn off the steps "
                "that need them."
            )

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_KEY_MESSAGE)
        fingerprint = _key_fingerprint(context.api_key)
        # A failed run can leave a position in another account's list, and a new key means another account.
        resume = checkpoint if checkpoint and checkpoint.get("key") == fingerprint else None
        with _translated_errors():
            client, _ = connect(context.api_key)
            match step:
                case "suppression_groups":
                    yield _groups_page(client, context)
                case "suppressions":
                    yield from _fetch_suppressions(client, context, resume, fingerprint)
                case "global_unsubscribes":
                    yield from _fetch_global_unsubscribes(client, context, resume, fingerprint)
                case "group_unsubscribes":
                    yield from _fetch_group_unsubscribes(client, context, resume, fingerprint)
                case "templates":
                    yield from _fetch_templates(client, context, resume, fingerprint)
                case "designs":
                    yield from _fetch_designs(client, context, resume, fingerprint)
                case "single_sends":
                    yield from _fetch_single_sends(client, context, resume, fingerprint)
                case "lists":
                    yield from _fetch_lists(client, context)
                case "senders":
                    yield from _fetch_senders(client, context, resume, fingerprint)
                case "domains":
                    yield from _fetch_domains(client, context, resume, fingerprint)
                case _:
                    raise UnknownImportStep(f"SendGrid has no import step named {step}.")


def missing_scopes(scopes: set[str], steps: list[str]) -> list[str]:
    """The first scope of each requirement the key can't meet, for the steps selected."""
    missing: list[str] = []
    for step in steps:
        for accepted in STEP_SCOPES.get(step, ()):
            if not scopes.intersection(accepted) and accepted[0] not in missing:
                missing.append(accepted[0])
    return missing


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except SendGridScopeMissing as e:
        raise ImportCredentialsInvalid(
            f"This SendGrid API key can't read {e.path}. Give it read access to that data, or turn off this step."
        ) from e
    except SendGridKeyRejected as e:
        raise ImportCredentialsInvalid(INVALID_KEY_MESSAGE) from e
    except SendGridRateLimited as e:
        raise ImportProviderUnavailable(RATE_LIMITED_MESSAGE) from e
    except SendGridAPIError as e:
        raise ImportProviderUnavailable(str(e)) from e


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


def _normalized_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.strip().lower()
    return email if email_domain(email) and not email.startswith("@") and len(email) <= 512 else None


def _contact_email(value: Any) -> str | None:
    # Unlike a suppression row, an opt-out matches the address a send names exactly, so the case stays as SendGrid has it.
    return value.strip() if _normalized_email(value) else None


def _timestamp(value: Any) -> datetime | None:
    # SendGrid writes these as Unix seconds. A value out of range or of another type says nothing useful.
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (ValueError, OverflowError, OSError):
        return None


def _group_key(group_id: Any) -> str:
    return f"{GROUP_KEY_PREFIX}{group_id}"[:64]


def _to_category(group: dict[str, Any]) -> ImportedCategory | None:
    group_id = group.get("id")
    if group_id is None:
        return None
    return ImportedCategory(
        key=_group_key(group_id),
        name=str(group.get("name") or group_id)[:128],
        description=str(group.get("description") or ""),
    )


def _groups_page(client: SendGridClient, context: ImportContext) -> ImportPage:
    groups = _read_groups(client)
    return ImportPage(processed=len(groups), save=partial(_save_groups, context, groups))


def _read_unless_deleted(client: SendGridClient, path: str) -> Any:
    # Something listed a moment ago can be gone by now, and that shouldn't fail the rest of the step.
    try:
        return client.get(path)
    except SendGridAPIError as e:
        if e.status_code == 404:
            return None
        raise


def _read_groups(client: SendGridClient) -> list[dict[str, Any]]:
    groups = client.get("/v3/asm/groups")
    if not isinstance(groups, list):
        raise SendGridAPIError("SendGrid sent an unexpected response for /v3/asm/groups.")
    return [group for group in groups if isinstance(group, dict)]


def _save_groups(context: ImportContext, groups: list[dict[str, Any]]) -> SavedPage:
    categories = [category for category in map(_to_category, groups) if category]
    result = import_categories(context.team_id, categories, context.created_by_id)
    return SavedPage(
        imported=result.created,
        counts={"created": result.created, "already_present": result.already_present},
        warnings=tuple(
            f"{group.get('name') or group.get('id')}: this is your default group in SendGrid, which applies to sends "
            "that name no group. PostHog has no default category, so choose one when you send."
            for group in groups
            if group.get("is_default") is True
        ),
    )


def _offset_checkpoint(fingerprint: str, list_key: str, offset: int, end_time: int) -> StepCheckpoint:
    return {"key": fingerprint, "list": list_key, "offset": offset, "end_time": end_time}


def _fetch_suppressions(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    # Lists have no cursor, only an offset. Pinning the end of the range keeps offsets valid while new entries arrive.
    end_time = int(resume["end_time"]) if resume and "end_time" in resume else int(timezone.now().timestamp())
    reached = resume is None
    for list_key, path, source, reason in SUPPRESSION_LISTS:
        if not reached and resume and resume.get("list") != list_key:
            continue
        offset = int(resume["offset"]) if not reached and resume else 0
        reached = True
        for page in client.offset_pages(path, offset=offset, params={"end_time": end_time}):
            yield ImportPage(
                processed=len(page.data),
                save=partial(_save_suppressions, context, page.data, list_key, source, reason),
                checkpoint=_offset_checkpoint(fingerprint, list_key, offset + len(page.data), end_time),
            )
            offset += len(page.data)


def _save_suppressions(
    context: ImportContext, entries: list[dict[str, Any]], list_key: str, source: SuppressionSource, reason: str
) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for entry in entries:
        email = _normalized_email(entry.get("email")) if isinstance(entry, dict) else None
        if email is None:
            invalid += 1
            continue
        imported[email] = ImportedSuppression(
            identifier=email,
            source=source,
            reason=reason,
            suppressed_at=_timestamp(entry.get("created")),
            diagnostic=str(entry.get("reason") or "")[:500] or None if source == SuppressionSource.BOUNCE else None,
        )
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
    added = result.added.get(source, 0)
    label = {"bounces": "bounced", "invalid": "invalid_addresses", "spam": "complained"}[list_key]
    return SavedPage(
        imported=result.total_added,
        counts={label: added, "already_present": result.already_present, "invalid": invalid},
    )


def _fetch_global_unsubscribes(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    end_time = int(resume["end_time"]) if resume and "end_time" in resume else int(timezone.now().timestamp())
    offset = int(resume["offset"]) if resume and "offset" in resume else 0
    for page in client.offset_pages("/v3/suppression/unsubscribes", offset=offset, params={"end_time": end_time}):
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_global_unsubscribes, context, page.data),
            checkpoint=_offset_checkpoint(fingerprint, "global", offset + len(page.data), end_time),
        )
        offset += len(page.data)


def _save_global_unsubscribes(context: ImportContext, entries: list[dict[str, Any]]) -> SavedPage:
    emails = {_contact_email(entry.get("email")) if isinstance(entry, dict) else None for entry in entries}
    valid = {email: [ALL_MESSAGE_PREFERENCE_CATEGORY_ID] for email in emails if email}
    changed = import_opt_outs(context.team_id, valid, context.created_by_id)
    return SavedPage(imported=changed, counts={"opted_out": changed, "invalid": len(entries) - len(valid)})


def _fetch_group_unsubscribes(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    groups = sorted(
        (group for group in _read_groups(client) if group.get("id") is not None), key=lambda g: int(g["id"])
    )
    start_group = int(resume["group"]) if resume and "group" in resume else None
    for group in groups:
        group_id = int(group["id"])
        if start_group is not None and group_id < start_group:
            continue
        offset = int(resume["offset"]) if resume and group_id == start_group else 0
        # This endpoint has no paging, so the whole group arrives at once. Sorted, a saved offset still means the same
        # place when a retry reads the group again.
        emails = sorted(
            str(email) for email in _read_unless_deleted(client, f"/v3/asm/groups/{group_id}/suppressions") or []
        )
        category = _to_category(group)
        while offset < len(emails) or (offset == 0 and not emails):
            chunk = emails[offset : offset + OPT_OUT_PAGE_SIZE]
            offset += OPT_OUT_PAGE_SIZE
            yield ImportPage(
                processed=len(chunk),
                save=partial(_save_group_unsubscribes, context, category, chunk),
                checkpoint={"key": fingerprint, "group": group_id, "offset": offset},
            )
            if not emails:
                break


def _save_group_unsubscribes(context: ImportContext, category: ImportedCategory | None, emails: list[str]) -> SavedPage:
    # A step's selection doesn't have to include the groups step, so the category may not exist yet.
    ids_by_key = import_categories(context.team_id, [category] if category else [], context.created_by_id).ids_by_key
    category_id = ids_by_key.get(category.key) if category else None
    valid = {address for address in map(_contact_email, emails) if address}
    # A category someone deleted in PostHog has no id here, and stays deleted.
    changed = import_opt_outs(
        context.team_id, {address: [category_id] for address in valid} if category_id else {}, context.created_by_id
    )
    return SavedPage(imported=changed, counts={"opted_out": changed, "invalid": len(emails) - len(valid)})


def _token_checkpoint(fingerprint: str, next_position: str | int | None) -> StepCheckpoint | None:
    return {"key": fingerprint, "page_token": str(next_position)} if next_position else None


def _page_token(resume: StepCheckpoint | None) -> str | None:
    return str(resume["page_token"]) if resume and resume.get("page_token") else None


def _fetch_templates(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    pages = client.token_pages("/v3/templates", _page_token(resume), TEMPLATE_PAGE_SIZE, generations="legacy,dynamic")
    for page in pages:
        templates = [(template, _read_active_version(client, template)) for template in page.data]
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_templates, context, templates),
            checkpoint=_token_checkpoint(fingerprint, page.next_position),
        )


def _read_active_version(client: SendGridClient, template: dict[str, Any]) -> dict[str, Any] | None:
    # The list holds a version's details, and only reading the version is documented to give its content and test data.
    version = _chosen_version(template)
    if version is None:
        return None
    return _read_unless_deleted(client, f"/v3/templates/{template['id']}/versions/{version['id']}")


def _chosen_version(template: dict[str, Any]) -> dict[str, Any] | None:
    versions = [
        version for version in template.get("versions") or [] if isinstance(version, dict) and version.get("id")
    ]
    active = next((version for version in versions if version.get("active") == 1), None)
    if active:
        return active
    return max(versions, key=lambda version: str(version.get("updated_at") or ""), default=None)


def _save_templates(context: ImportContext, templates: list[tuple[dict[str, Any], dict[str, Any] | None]]) -> SavedPage:
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = _taken_keys(context.team_id, [str(template.get("id")) for template, _ in templates])
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for template, version in templates:
        key = str(template.get("id"))
        name = str(template.get("name") or key)[:400]
        if key in taken:
            counts["already_present"] += 1
            items.append(ImportItem(label=name, status="skipped", notes=(f"A template with the key {key} exists.",)))
            continue
        if version is None:
            counts["no_version"] += 1
            items.append(
                ImportItem(label=name, status="skipped", notes=("This template has no version to read in SendGrid.",))
            )
            continue
        taken.add(key)
        converted = convert_version(version, generation=str(template.get("generation") or "legacy"))
        notes = (*_version_notes(template, version), *converted.notes, *converted.send_notes, _SENDER_NOTE)
        items.append(_create(context, key, name, converted, notes, _sample_data_line(version), counts))
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


_SENDER_NOTE = "SendGrid sets the sender on each send. Choose one on this template before you send it."


def _version_notes(template: dict[str, Any], version: dict[str, Any]) -> tuple[str, ...]:
    versions = [other for other in template.get("versions") or [] if isinstance(other, dict)]
    others = [str(other.get("name") or other.get("id")) for other in versions if other.get("id") != version.get("id")]
    notes: list[str] = []
    if version.get("active") != 1:
        notes.append(f"No version is active in SendGrid, so PostHog imported {version.get('name')}, the newest.")
    if others:
        notes.append(f"Only one version came across. These stay in SendGrid: {', '.join(others)}.")
    return tuple(notes)


def _sample_data_line(version: dict[str, Any]) -> str:
    sample = version.get("test_data")
    if not sample or not isinstance(sample, str | dict):
        return ""
    text = sample if isinstance(sample, str) else json.dumps(sample)
    if len(text) > MAX_SAMPLE_DATA_LENGTH:
        return "SendGrid's test data for this template was too long to keep here."
    return f"Test data from SendGrid: {text}"


def _taken_keys(team_id: int, keys: list[str]) -> set[str]:
    return set(MessageTemplate.objects.filter(team_id=team_id, key__in=keys).values_list("key", flat=True))


def _create(
    context: ImportContext,
    key: str,
    name: str,
    converted: ConvertedSendGridTemplate,
    notes: tuple[str, ...],
    sample_line: str,
    counts: Counter[str],
    sender: dict[str, Any] | None = None,
    category_id: str | None = None,
) -> ImportItem:
    email: dict[str, Any] = {"subject": converted.subject, "html": converted.html}
    if converted.text:
        email["text"] = converted.text
    if sender:
        email["from"] = sender
    fields: dict[str, Any] = {
        "name": name,
        "key": key,
        "description": " ".join(part for part in ("Imported from SendGrid.", *notes, sample_line) if part),
        "type": "email",
        "content": {"templating": "liquid", "email": email},
        "tags": [IMPORT_TAG],
    }
    if category_id:
        fields["message_category"] = category_id
    created = create_template(context.team_id, context.created_by_id, fields)
    counts["needs_review" if notes else "created"] += 1
    return ImportItem(label=name, status="created", url=f"/workflows/library/templates/{created.id}", notes=notes)


def _fetch_designs(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    for page in client.token_pages("/v3/designs", _page_token(resume), 100):
        read = [_read_unless_deleted(client, f"/v3/designs/{design['id']}") for design in page.data if design.get("id")]
        designs = [design for design in read if design]
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_designs, context, designs),
            checkpoint=_token_checkpoint(fingerprint, page.next_position),
        )


def _save_designs(context: ImportContext, designs: list[dict[str, Any]]) -> SavedPage:
    keys = {str(design["id"]): f"sendgrid-design-{design['id']}"[:400] for design in designs}
    taken = _taken_keys(context.team_id, list(keys.values()))
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for design in designs:
        key = keys[str(design["id"])]
        name = str(design.get("name") or key)[:400]
        if key in taken:
            counts["already_present"] += 1
            items.append(ImportItem(label=name, status="skipped", notes=(f"A template with the key {key} exists.",)))
            continue
        converted = convert_version(design)
        notes = (*converted.notes, *converted.send_notes, _SENDER_NOTE)
        items.append(_create(context, key, name, converted, notes, "", counts))
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _fetch_single_sends(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    senders: dict[int, dict[str, Any] | None] = {}
    for page in client.token_pages("/v3/marketing/singlesends", _page_token(resume), 100):
        details = []
        for summary in page.data:
            if not summary.get("id"):
                continue
            single_send = _read_unless_deleted(client, f"/v3/marketing/singlesends/{summary['id']}")
            if not single_send:
                continue
            config = single_send.get("email_config") or {}
            # A design replaces whichever of the content fields it holds.
            design = (
                _read_unless_deleted(client, f"/v3/designs/{config['design_id']}") if config.get("design_id") else None
            )
            sender_id = config.get("sender_id")
            if isinstance(sender_id, int) and sender_id not in senders:
                senders[sender_id] = _read_sender(client, sender_id)
            details.append((single_send, design))
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_single_sends, context, details, dict(senders)),
            checkpoint=_token_checkpoint(fingerprint, page.next_position),
        )


def _read_sender(client: SendGridClient, sender_id: int) -> dict[str, Any] | None:
    try:
        results = client.get("/v3/verified_senders", {"id": sender_id}).get("results") or []
    except SendGridScopeMissing:
        return None
    return results[0] if results else None


def _save_single_sends(
    context: ImportContext,
    details: list[tuple[dict[str, Any], dict[str, Any] | None]],
    senders: Mapping[int, dict[str, Any] | None],
) -> SavedPage:
    keys = {str(single_send["id"]): f"sendgrid-singlesend-{single_send['id']}"[:400] for single_send, _ in details}
    taken = _taken_keys(context.team_id, list(keys.values()))
    posthog_senders = _senders(context.team_id)
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for single_send, design in details:
        key = keys[str(single_send["id"])]
        name = str(single_send.get("name") or key)[:400]
        if key in taken:
            counts["already_present"] += 1
            items.append(ImportItem(label=name, status="skipped", notes=(f"A template with the key {key} exists.",)))
            continue
        config = single_send.get("email_config") or {}
        version = {**config, **{k: v for k, v in (design or {}).items() if v not in (None, "")}}
        converted = convert_version(version, contact_fields=True)
        sender, sender_notes = _single_send_sender(config, senders, posthog_senders)
        category_id, group_notes = _single_send_category(context.team_id, config)
        notes = (
            *_single_send_notes(single_send),
            *converted.notes,
            *converted.send_notes,
            *sender_notes,
            *group_notes,
        )
        items.append(_create(context, key, name, converted, notes, "", counts, sender, category_id))
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _single_send_notes(single_send: dict[str, Any]) -> tuple[str, ...]:
    notes = [
        "Who this goes to doesn't come across, because it's a list of SendGrid contacts. Choose an audience in a "
        "workflow."
    ]
    if single_send.get("status") == "scheduled":
        notes.insert(
            0,
            f"This is still scheduled in SendGrid for {single_send.get('send_at')}. Cancel it there if you "
            "don't want it to go out.",
        )
    if single_send.get("is_abtest"):
        notes.append("This is an A/B test in SendGrid. PostHog imported its main content, not its other variants.")
    return tuple(notes)


def _single_send_sender(
    config: dict[str, Any],
    senders: Mapping[int, dict[str, Any] | None],
    posthog_senders: Mapping[str, IntegrationRecord],
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    sender = senders.get(config.get("sender_id")) if isinstance(config.get("sender_id"), int) else None
    if not sender or not sender.get("from_email"):
        return None, ("Choose a sender on this template before you send it.",)
    address = str(sender["from_email"])
    integration = posthog_senders.get(address.lower())
    if integration is None:
        return None, (f"{address} isn't a PostHog sender yet. Add it, then choose it on this template.",)
    return (
        {"integrationId": integration.id, "email": address, "name": str(sender.get("from_name") or "")},
        () if integration.config.get("verified") else (f"{address} isn't verified in PostHog yet.",),
    )


def _single_send_category(team_id: int, config: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    group_id = config.get("suppression_group_id")
    custom_url = config.get("custom_unsubscribe_url")
    notes = (
        (f"This used your own unsubscribe link, {custom_url}. PostHog links to its preferences page instead.",)
        if custom_url
        else ()
    )
    if group_id is None:
        return None, notes
    row = MessageCategory.objects.filter(team_id=team_id, key=_group_key(group_id), deleted=False).first()
    if row is None:
        return None, (*notes, "Import unsubscribe groups, then choose this email's category on the template.")
    return str(row.id), notes


def _senders(team_id: int) -> dict[str, IntegrationRecord]:
    return {
        str(sender.config.get("email", "")).lower(): sender
        for sender in IntegrationManager.email.credentials.list(team_id)
    }


def _fetch_lists(client: SendGridClient, context: ImportContext) -> Iterator[ImportPage]:
    lists: list[dict[str, Any]] = []
    for page in client.token_pages("/v3/marketing/lists", None, 1000):
        lists.extend(row for row in page.data if isinstance(row, dict))
    count = client.get("/v3/marketing/contacts/count")
    contacts = count.get("contact_count") if isinstance(count, dict) else 0
    yield ImportPage(
        processed=len(lists), save=partial(_save_lists, lists, contacts if isinstance(contacts, int) else 0)
    )


def _save_lists(lists: list[dict[str, Any]], contacts: int) -> SavedPage:
    return SavedPage(
        imported=0,
        counts={"lists": len(lists), "contacts": contacts},
        items=tuple(
            ImportItem(
                label=str(row.get("name") or row.get("id")),
                status="listed",
                url="/cohorts",
                notes=(f"{row.get('contact_count', 0)} contacts. Rebuild this list as a cohort of your users.",),
            )
            for row in lists
        ),
    )


def _fetch_senders(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    page_size = 100
    last_seen = resume.get("last_seen") if resume else None
    while True:
        params: dict[str, Any] = {"limit": page_size}
        if last_seen is not None:
            params["lastSeenID"] = last_seen
        body = client.get("/v3/verified_senders", params)
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise SendGridAPIError("SendGrid sent an unexpected response for /v3/verified_senders.")
        more = len(results) == page_size and results[-1].get("id") not in (None, last_seen)
        last_seen = results[-1].get("id") if more else None
        yield ImportPage(
            processed=len(results),
            save=partial(_save_senders, context, results),
            checkpoint={"key": fingerprint, "last_seen": last_seen} if more else None,
        )
        if not more:
            return


def _save_senders(context: ImportContext, results: list[dict[str, Any]]) -> SavedPage:
    posthog_senders = _senders(context.team_id)
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for sender in results:
        address = str(sender.get("from_email") or "")
        integration = posthog_senders.get(address.lower())
        ready = bool(integration and integration.config.get("verified"))
        counts["ready" if ready else "needs_setup"] += 1
        notes: list[str] = []
        if not ready:
            notes.append("Waiting for DNS." if integration else "Add this sender's domain in PostHog to send from it.")
        if sender.get("verified") is False:
            notes.append("SendGrid hasn't verified this sender either.")
        name = str(sender.get("from_name") or "")
        items.append(
            ImportItem(
                label=f"{name} <{address}>" if name else address,
                status="listed",
                url=f"/workflows/channels/email/{integration.id}" if integration else "/workflows/channels",
                notes=tuple(notes),
            )
        )
    return SavedPage(imported=0, counts=dict(counts), items=tuple(items))


def _fetch_domains(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    offset = int(resume["offset"]) if resume and "offset" in resume else 0
    for page in client.offset_pages("/v3/whitelabel/domains", offset=offset, page_size=50):
        offset += len(page.data)
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_domains, context, page.data),
            checkpoint={"key": fingerprint, "offset": offset} if page.next_position is not None else None,
        )


def _save_domains(context: ImportContext, domains: list[dict[str, Any]]) -> SavedPage:
    senders_by_domain: dict[str, list[IntegrationRecord]] = {}
    for sender in IntegrationManager.email.credentials.list(context.team_id):
        senders_by_domain.setdefault(str(sender.config.get("domain", "")).lower(), []).append(sender)
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for domain in domains:
        name = str(domain.get("domain") or "")
        senders = senders_by_domain.get(name.lower(), [])
        ready = any(sender.config.get("verified") for sender in senders)
        counts["ready" if ready else "needs_setup"] += 1
        notes: list[str] = []
        if not ready:
            notes.append(
                "Waiting for DNS. Check the records on this domain's page."
                if senders
                else "Add this domain in PostHog to get its DNS records."
            )
        records = ", ".join(_dns_hosts(domain))
        if records:
            notes.append(f"Keep SendGrid's records until nothing sends through it: {records}.")
        if str(domain.get("subdomain") or "").lower() == MAIL_FROM_DEFAULT:
            notes.append(
                f"SendGrid already uses the {MAIL_FROM_DEFAULT} subdomain here. Choose a different MAIL FROM subdomain "
                "in PostHog, or both tools will claim the same name in DNS and one of them will break."
            )
        items.append(
            ImportItem(
                label=name,
                status="listed",
                url=f"/workflows/channels/email/{senders[0].id}" if senders else "/workflows/channels",
                notes=tuple(notes),
            )
        )
    return SavedPage(imported=0, counts=dict(counts), items=tuple(items))


def _dns_hosts(domain: dict[str, Any]) -> list[str]:
    dns = domain.get("dns") if isinstance(domain.get("dns"), dict) else {}
    return [str(record["host"]) for record in dns.values() if isinstance(record, dict) and record.get("host")]
