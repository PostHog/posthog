"""Imports suppressions, unsubscribe groups and templates from SendGrid, and lists what can't move.

SendGrid is the one provider here with read-only scopes, so the customer can hand over a narrow key. The run still only
keeps it until it ends. SendGrid documents only stats for its automations, so they stay behind. Contacts become people
only in the contacts step, matched by email. SendGrid shares a whole list only as an export it prepares in the
background, as a file to download.
"""

import io
import csv
import json
import time
import hashlib
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from itertools import chain
from typing import IO, Any, Literal
from urllib.parse import quote

from django.utils import timezone

from posthog.dataclasses import frozen
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
    ImportTooLarge,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.provider_imports.contacts import (
    CONTACT_COUNT_LABELS,
    MAX_CONTACT_BYTES,
    MAX_CONTACT_MEMBERSHIPS,
    TOO_MANY_CONTACTS_MESSAGE,
    ContactCollector,
    ContactList,
    new_people_page,
    new_people_step,
    save_contact_lists,
)
from products.messaging.backend.provider_imports.emails import exact_email, normalized_email
from products.messaging.backend.provider_imports.liquid_text import literal_liquid
from products.messaging.backend.provider_imports.senders import sender_for_address
from products.messaging.backend.provider_imports.sendgrid_templates import ConvertedSendGridTemplate, convert_version
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    carry_opt_outs,
    code_email_keys,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.message_templates import create_template, with_editor_design
from products.messaging.backend.services.sendgrid_client import (
    SUPPRESSION_PAGE_SIZE,
    TEMPLATE_PAGE_SIZE,
    SendGridAPIError,
    SendGridClient,
    SendGridDownloadIncomplete,
    SendGridKeyRejected,
    SendGridRateLimited,
    SendGridResponseTooLarge,
    SendGridScopeMissing,
    connect,
)
from products.workflows.backend.facade.people_import import MAX_SOURCE_NAME_LENGTH

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
CONTACTS_FLAG = "workflows-sendgrid-contacts-import"
# Each list becomes its own cohort, and the contacts step saves them all in one transaction.
MAX_LISTS = 500
TOO_MANY_LISTS_MESSAGE = (
    f"This account has more than {MAX_LISTS} lists, more than one import takes. Upload the ones you need as "
    "CSV files instead."
)
EXPORT_POLL_SECONDS = 5
EXPORT_TIMEOUT_SECONDS = 60 * 60
# The export of every contact, next to the exports named by their list's ID.
ALL_CONTACTS = "all"
NO_CONTACTS_NOTE = "SendGrid has no contacts to import, so every cohort stays as it was."
# SendGrid doesn't say how far its counts lag, so only a difference that no lag explains stops an import.
COUNT_SLACK = 10
UNREADABLE_EXPORT_MESSAGE = "SendGrid's contact export isn't a file PostHog can read. Import again later."
# SendGrid's own fields, which an export names in capitals. Any other column is one of the account's custom fields.
CONTACT_FIELDS = frozenset(
    {
        "first_name",
        "last_name",
        "phone_number",
        "whatsapp",
        "line",
        "facebook",
        "unique_name",
        "address_line_1",
        "address_line_2",
        "city",
        "state_province_region",
        "postal_code",
        "country",
    }
)
# Columns that identify a contact inside SendGrid, or describe its record there.
_RECORD_FIELDS = frozenset(
    {
        "email",
        "alternate_emails",
        "contact_id",
        "phone_number_id",
        "external_id",
        "anonymous_id",
        "list_ids",
        "lists",
        "segment_ids",
        "created_at",
        "updated_at",
        "email_domains",
        "last_clicked",
        "last_emailed",
        "last_opened",
        "singlesend_id",
        "automation_id",
    }
)

# A step's scopes, as SendGrid enforces them. A tuple means any one of them is enough. SendGrid refuses the suppression
# lists and group members to a key with only the per-list scopes its docs name, so these need suppression.read. Verified
# senders are missing because no restricted scope reads them, so a key that can't read those fails on the step itself
# with a message naming it.
STEP_SCOPES: dict[str, tuple[tuple[str, ...], ...]] = {
    "suppression_groups": (("asm.groups.read",),),
    "suppressions": (("suppression.read",),),
    "global_unsubscribes": (("suppression.read",),),
    "group_unsubscribes": (("asm.groups.read",), ("suppression.read",)),
    "templates": (("templates.read",), ("templates.versions.read",)),
    "designs": (("design_library.read",),),
    # A Single Send built from a design reads that design.
    "single_sends": (("marketing.read",), ("design_library.read",)),
    "lists": (("marketing.read",),),
    # Reads every suppression and unsubscribe again, once the exports are in.
    "contacts": (("marketing.read",), ("suppression.read",), ("asm.groups.read",), ("user.username.read",)),
    "domains": (("whitelabel.read",),),
}
# SendGrid grants no marketing scope at all to a key on an account without Marketing Campaigns, even with full access.
# A key that was given none on purpose looks the same, so these steps skip with a note instead of refusing the key.
MARKETING_STEPS = ("single_sends", "lists", "contacts")
# With contacts, a new run reads these from the start. Continuing a failed run would skip who opted out since then, and
# those contacts could get marketing email.
OPT_OUT_STEPS = ("suppressions", "global_unsubscribes", "group_unsubscribes")
NO_MARKETING_CAMPAIGNS_NOTE = (
    "Skipped, because this key can't read Marketing Campaigns. Accounts without a Marketing Campaigns plan have "
    "nothing to import here. If your account has one, give the key marketing.read and design_library.read, then "
    "import again."
)
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
        "SendGrid doesn't keep suppressing those addresses either. Webhooks, API keys, "
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
            description="Adds these to your PostHog suppression list. Needs suppression.read.",
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
                "PostHog doesn't. Needs suppression.read."
            ),
            count_labels=(("opted_out", "Newly opted out"), ("invalid", "Skipped because the address isn't valid")),
        ),
        ImportStepSpec(
            key="group_unsubscribes",
            label="Group unsubscribes",
            description=(
                "Opts people out of the category for each group they left. Needs asm.groups.read and suppression.read."
            ),
            count_labels=(
                ("opted_out", "New opt-outs, counted per group"),
                ("invalid", "Skipped, address isn't valid"),
            ),
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
            description="Copies each design you saved into your PostHog library as a template. Needs design_library.read.",
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
                "write to your marketing data, and design_library.read."
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
                "Lists your contact lists and how many people are on them, so you know what to rebuild. Needs "
                "marketing.read, which SendGrid also lets write to your marketing data."
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
        # Needs the opt-out steps in the same run and after them, so no imported contact can be sent marketing email
        # they left in SendGrid.
        ImportStepSpec(
            key="contacts",
            label="Contacts",
            description=(
                "Matches each contact to a person in PostHog by email and fills in their contact fields where PostHog "
                "has none. Fills a cohort with all your contacts, one with each list's and one with each segment's current "
                "contacts, without those who unsubscribed from everything. Import again to refresh them. Each subuser gets "
                "its own cohort of all contacts. SendGrid prepares an export of each one, which can take a while. Select "
                "all three steps for suppressions and unsubscribes too, so no one who left in SendGrid gets marketing "
                "email. Needs marketing.read, suppression.read, asm.groups.read and user.username.read."
            ),
            count_labels=CONTACT_COUNT_LABELS,
            requires=OPT_OUT_STEPS,
            needs=OPT_OUT_STEPS,
            counts_as_events=True,
            feature_flag=CONTACTS_FLAG,
            hidden_note="Contacts don't become people, and segments stay in SendGrid.",
        ),
        new_people_step("SendGrid", CONTACTS_FLAG),
    )

    def check_credentials(
        self, team_id: int, api_key: str | None, settings: Mapping[str, str], steps: Sequence[str]
    ) -> ImportCredentials:
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
        message = missing_scopes_message(missing_scopes_by_step(scopes, steps), self.steps)
        if message:
            raise ImportCredentialsInvalid(message)

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_KEY_MESSAGE)
        fingerprint = _key_fingerprint(context.api_key)
        if step == "contacts" or (step in OPT_OUT_STEPS and "contacts" in context.steps):
            fingerprint = f"{fingerprint}/{context.run_id}"
        # A failed run can leave a position in another account's list, and a new key means another account.
        resume = checkpoint if checkpoint and checkpoint.get("key") == fingerprint else None
        with _translated_errors():
            client, scopes = connect(context.api_key)
            if step in MARKETING_STEPS and not _has_marketing_campaigns(scopes):
                yield ImportPage(processed=0, save=_save_no_marketing_campaigns)
                return
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
                case "contacts":
                    yield from _fetch_contacts(client, context, resume, fingerprint)
                case "new_people":
                    yield ImportPage(processed=0, save=new_people_page)
                case "senders":
                    yield from _fetch_senders(client, context, resume, fingerprint)
                case "domains":
                    yield from _fetch_domains(client, context, resume, fingerprint)
                case _:
                    raise UnknownImportStep(f"SendGrid has no import step named {step}.")


def missing_scopes_by_step(scopes: set[str], steps: Sequence[str]) -> dict[str, list[str]]:
    """Each scope the key lacks, with the selected steps that need it. Marketing steps on an account without Marketing
    Campaigns run anyway and say there's nothing to import."""
    missing: dict[str, list[str]] = {}
    for step in steps:
        if step in MARKETING_STEPS and not _has_marketing_campaigns(scopes):
            continue
        for accepted in STEP_SCOPES.get(step, ()):
            if not scopes.intersection(accepted):
                missing.setdefault(accepted[0], []).append(step)
    return missing


def missing_scopes_message(missing: Mapping[str, list[str]], specs: Sequence[ImportStepSpec]) -> str | None:
    if not missing:
        return None
    labels = {spec.key: spec.label for spec in specs}
    by_steps: dict[tuple[str, ...], list[str]] = {}
    for scope, needing_steps in missing.items():
        by_steps.setdefault(tuple(needing_steps), []).append(scope)
    if len(by_steps) == 1:
        [(steps, scope_names)] = by_steps.items()
        step_names = _and_list([labels[s] for s in steps])
        pronoun = "it" if len(scope_names) == 1 else "them"
        if len(steps) == 1:
            needed_by, turn_off = f"the {step_names} step needs", "that step"
        else:
            needed_by, turn_off = f"the {step_names} steps need", "those steps"
        return (
            f"This SendGrid API key is missing {_and_list(scope_names)}, which {needed_by}. Add {pronoun} in SendGrid, "
            f"or turn off {turn_off}."
        )
    parts = [
        f"{_and_list(scope_names)} (for {_and_list([labels[s] for s in steps])})"
        for steps, scope_names in by_steps.items()
    ]
    return (
        f"This SendGrid API key is missing {_and_list(parts)}. Add them in SendGrid, or turn off the steps that "
        "need them."
    )


def _and_list(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _has_marketing_campaigns(scopes: set[str]) -> bool:
    return any(scope.startswith("marketing.") for scope in scopes)


def _save_no_marketing_campaigns() -> SavedPage:
    return SavedPage(imported=0, warnings=(NO_MARKETING_CAMPAIGNS_NOTE,))


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
    except SendGridResponseTooLarge as e:
        raise ImportTooLarge(str(e)) from e
    except SendGridAPIError as e:
        raise ImportProviderUnavailable(str(e)) from e


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()[:16]


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


def _offset_checkpoint(fingerprint: str, list_key: str, offset: int, end_time: int, last: str | None) -> StepCheckpoint:
    checkpoint: StepCheckpoint = {"key": fingerprint, "list": list_key, "offset": offset, "end_time": end_time}
    if last is not None:
        checkpoint["last"] = last
    return checkpoint


def _list_email(row: Any) -> str | None:
    return str(row["email"]) if isinstance(row, dict) and row.get("email") else None


def _list_rows(client: SendGridClient, path: str, offset: int, end_time: int) -> list[Any]:
    rows = client.get(path, {"end_time": end_time, "limit": SUPPRESSION_PAGE_SIZE, "offset": offset})
    if not isinstance(rows, list):
        raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.")
    return rows


def _offset_after(client: SendGridClient, path: str, position: int, last: str, end_time: int) -> tuple[int, str | None]:
    # A deleted entry only moves later ones back, so the last row read is somewhere before where it was.
    while position > 0:
        start = max(position - SUPPRESSION_PAGE_SIZE, 0)
        rows = _list_rows(client, path, start, end_time)
        for index, row in enumerate(rows[: position - start]):
            if _list_email(row) == last:
                return start + index + 1, last
        position = start
    # It was deleted too. Saving an address twice changes nothing, so read the list again from the start.
    return 0, None


@frozen
class _ListPage:
    rows: list[Any]
    # Where to continue: the offset after these rows, and the email of the last one.
    offset: int
    last: str | None


def _list_pages_after(
    client: SendGridClient, path: str, offset: int, last: str | None, end_time: int
) -> Iterator[_ListPage]:
    """New rows of a suppression list, with the offset and email to continue after them.

    Lists have no cursor, only an offset. Pinning the end of the range keeps new entries out, but deleting an entry
    already read moves every later one back. So each page starts at the last row read, to check it's still there."""
    while True:
        start = offset - 1 if last is not None and offset > 0 else offset
        rows = _list_rows(client, path, start, end_time)
        if start < offset:
            if not rows or _list_email(rows[0]) != last:
                offset, last = _offset_after(client, path, start, last or "", end_time)
                continue
            fresh = rows[1:]
        else:
            fresh = rows
        if fresh:
            offset += len(fresh)
            last = _list_email(fresh[-1])
            yield _ListPage(rows=fresh, offset=offset, last=last)
        if len(rows) < SUPPRESSION_PAGE_SIZE:
            return


def _fetch_suppressions(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    end_time = int(resume["end_time"]) if resume and "end_time" in resume else int(timezone.now().timestamp())
    reached = resume is None
    for list_key, path, source, reason in SUPPRESSION_LISTS:
        if not reached and resume and resume.get("list") != list_key:
            continue
        start = int(resume["offset"]) if not reached and resume else 0
        anchor = str(resume["last"]) if not reached and resume and "last" in resume else None
        reached = True
        for page in _list_pages_after(client, path, start, anchor, end_time):
            yield ImportPage(
                processed=len(page.rows),
                save=partial(_save_suppressions, context, page.rows, list_key, source, reason),
                checkpoint=_offset_checkpoint(fingerprint, list_key, page.offset, end_time, page.last),
            )


def _save_suppressions(
    context: ImportContext, entries: list[dict[str, Any]], list_key: str, source: SuppressionSource, reason: str
) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for entry in entries:
        email = normalized_email(entry.get("email")) if isinstance(entry, dict) else None
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
    start = int(resume["offset"]) if resume and "offset" in resume else 0
    anchor = str(resume["last"]) if resume and "last" in resume else None
    for page in _list_pages_after(client, "/v3/suppression/unsubscribes", start, anchor, end_time):
        yield ImportPage(
            processed=len(page.rows),
            save=partial(_save_global_unsubscribes, context, page.rows),
            checkpoint=_offset_checkpoint(fingerprint, "global", page.offset, end_time, page.last),
        )


def _save_global_unsubscribes(context: ImportContext, entries: list[dict[str, Any]]) -> SavedPage:
    emails = {exact_email(entry.get("email")) if isinstance(entry, dict) else None for entry in entries}
    valid = {email: [ALL_MESSAGE_PREFERENCE_CATEGORY_ID] for email in emails if email}
    changed = import_opt_outs(context.team_id, valid, context.created_by_id)
    _carry_to_every_spelling(context, valid)
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
        # This endpoint has no paging, so the whole group arrives at once. A retry continues after the last saved
        # address, which still holds when members join or leave between attempts.
        emails = sorted(
            str(email) for email in _read_unless_deleted(client, f"/v3/asm/groups/{group_id}/suppressions") or []
        )
        after = resume.get("after") if resume and group_id == start_group else None
        offset = bisect_right(emails, str(after)) if after is not None else 0
        category = _to_category(group)
        while offset < len(emails) or (offset == 0 and not emails):
            chunk = emails[offset : offset + OPT_OUT_PAGE_SIZE]
            offset += OPT_OUT_PAGE_SIZE
            yield ImportPage(
                processed=len(chunk),
                save=partial(_save_group_unsubscribes, context, category, chunk),
                checkpoint={"key": fingerprint, "group": group_id, "after": chunk[-1] if chunk else ""},
            )
            if not emails:
                break


def _save_group_unsubscribes(context: ImportContext, category: ImportedCategory | None, emails: list[str]) -> SavedPage:
    # A step's selection doesn't have to include the groups step, so the category may not exist yet.
    ids_by_key = import_categories(context.team_id, [category] if category else [], context.created_by_id).ids_by_key
    category_id = ids_by_key.get(category.key) if category else None
    valid = {address for address in map(exact_email, emails) if address}
    # A category someone deleted in PostHog has no id here, and stays deleted.
    changed = import_opt_outs(
        context.team_id, {address: [category_id] for address in valid} if category_id else {}, context.created_by_id
    )
    if category_id:
        _carry_to_every_spelling(context, valid)
    return SavedPage(imported=changed, counts={"opted_out": changed, "invalid": len(emails) - len(valid)})


def _carry_to_every_spelling(context: ImportContext, addresses: Iterable[str]) -> None:
    # A send matches an opt-out by exact address, and SendGrid keeps the case the address arrived in.
    carry_opt_outs(
        context.team_id,
        [spelling for address in addresses for spelling in (address, address.lower())],
        context.created_by_id,
    )


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
            items.append(
                ImportItem(
                    label=name,
                    status="skipped",
                    notes=(
                        f"A template with the key {key} is already in PostHog, or was deleted there, so it stays as it is.",
                    ),
                )
            )
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


SENDERS_NEED_FULL_ACCESS = (
    "Only a full access SendGrid key can read your verified senders, so they weren't listed. Add the addresses you "
    "send from as senders in PostHog."
)
_SENDER_NOTE = "SendGrid sets the sender on each send. Choose one on this template before you send it."


def _version_notes(template: dict[str, Any], version: dict[str, Any]) -> tuple[str, ...]:
    versions = [other for other in template.get("versions") or [] if isinstance(other, dict)]
    others = [str(other.get("name") or other.get("id")) for other in versions if other.get("id") != version.get("id")]
    notes: list[str] = []
    if version.get("active") != 1:
        name = version.get("name")
        notes.append(
            f"No version is active in SendGrid, so PostHog imported {name}, the newest."
            if name
            else "No version is active in SendGrid, so PostHog imported the newest version."
        )
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
    rows = MessageTemplate.objects.filter(team_id=team_id, key__in=keys).values_list("key", flat=True)
    return {key for key in rows if key} | code_email_keys(team_id, keys)


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
    reply_to: str = "",
) -> ImportItem:
    email: dict[str, Any] = with_editor_design({"subject": converted.subject, "html": converted.html})
    if converted.text:
        email["text"] = converted.text
    if sender:
        email["from"] = sender
    if reply_to:
        email["replyTo"] = reply_to
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
            items.append(
                ImportItem(
                    label=name,
                    status="skipped",
                    notes=(
                        f"A template with the key {key} is already in PostHog, or was deleted there, so it stays as it is.",
                    ),
                )
            )
            continue
        converted = convert_version(design, contact_fields=True)
        notes = (*converted.notes, *converted.send_notes, _SENDER_NOTE)
        items.append(_create(context, key, name, converted, notes, "", counts))
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _fetch_single_sends(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    senders: dict[int, dict[str, Any]] | None = None
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
            if senders is None and isinstance(config.get("sender_id"), int):
                senders = _all_verified_senders(client)
            details.append((single_send, design))
        yield ImportPage(
            processed=len(page.data),
            save=partial(_save_single_sends, context, details, dict(senders or {})),
            checkpoint=_token_checkpoint(fingerprint, page.next_position),
        )


def _all_verified_senders(client: SendGridClient) -> dict[int, dict[str, Any]]:
    """Every verified sender by id. SendGrid's list has no filter by id, so it's read page by page."""
    senders: dict[int, dict[str, Any]] = {}
    last_seen = None
    while True:
        params: dict[str, Any] = {"limit": 100, **({"lastSeenID": last_seen} if last_seen is not None else {})}
        try:
            body = client.get("/v3/verified_senders", params)
        except SendGridScopeMissing:
            return senders
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list) or not results:
            return senders
        senders.update({row["id"]: row for row in results if isinstance(row, dict) and isinstance(row.get("id"), int)})
        if len(results) < 100 or results[-1].get("id") in (None, last_seen):
            return senders
        last_seen = results[-1].get("id")


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
            items.append(
                ImportItem(
                    label=name,
                    status="skipped",
                    notes=(
                        f"A template with the key {key} is already in PostHog, or was deleted there, so it stays as it is.",
                    ),
                )
            )
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
        items.append(
            _create(
                context,
                key,
                name,
                converted,
                notes,
                "",
                counts,
                sender,
                category_id,
                _single_send_reply_to(config, senders),
            )
        )
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
    sender_id = config.get("sender_id")
    sender = senders.get(sender_id) if isinstance(sender_id, int) else None
    if not sender or not sender.get("from_email"):
        return None, ("Choose a sender on this template before you send it.",)
    address = str(sender["from_email"])
    integration = sender_for_address(address, posthog_senders)
    if integration is None:
        return None, (f"{address} isn't a PostHog sender yet. Add it, then choose it on this template.",)
    return (
        {
            "integrationId": integration.id,
            "email": literal_liquid(address),
            "name": literal_liquid(str(sender.get("from_name") or "")),
        },
        () if integration.config.get("verified") else (f"{address} isn't verified in PostHog yet.",),
    )


def _single_send_reply_to(config: dict[str, Any], senders: Mapping[int, dict[str, Any] | None]) -> str:
    sender_id = config.get("sender_id")
    sender = senders.get(sender_id) if isinstance(sender_id, int) else None
    return literal_liquid(str((sender or {}).get("reply_to") or ""))


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
        processed=len(lists),
        save=partial(_save_lists, lists, contacts if isinstance(contacts, int) else 0, "contacts" in context.steps),
    )


def _save_lists(lists: list[dict[str, Any]], contacts: int, imports_contacts: bool) -> SavedPage:
    next_step = (
        "The Contacts step fills a cohort with them."
        if imports_contacts
        else "Rebuild this list as a cohort of your users."
    )
    return SavedPage(
        imported=0,
        counts={"lists": len(lists), "contacts": contacts},
        items=tuple(
            ImportItem(
                label=str(row.get("name") or row.get("id")),
                status="listed",
                url="/cohorts",
                notes=(f"{row.get('contact_count') or 0} contacts. {next_step}",),
            )
            for row in lists
        ),
    )


def _fetch_contacts(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    """Reads an export of every contact and one of each list and segment, then saves them together, so one that can't be
    read leaves every cohort as it was. The checkpoint holds the exports SendGrid already started, so a retry downloads
    those again rather than waiting for new ones."""
    account = _read_account(client)
    count = client.get("/v3/marketing/contacts/count")
    audiences = {audience.id: audience for audience in _read_audiences(client)}
    if sum(audience.kind == "list" for audience in audiences.values()) > MAX_LISTS:
        raise ImportTooLarge(TOO_MANY_LISTS_MESSAGE)
    exports: dict[str, str] = json.loads(str(resume["exports"])) if resume and "exports" in resume else {}
    contacts = ContactCollector()
    custom_fields = _read_custom_fields(client)
    skipped: dict[str, str] = json.loads(str(resume["skipped"])) if resume and "skipped" in resume else {}
    audiences = {key: audience for key, audience in audiences.items() if key not in skipped}
    # Lists come first, so only segments pass the limit.
    for extra in list(audiences.values())[MAX_LISTS:]:
        del audiences[extra.id]
        skipped[extra.id] = _skipped_note(extra, f"This account has more than {MAX_LISTS} lists and segments.")
    segments_deadline: float | None = None
    memberships = 0
    audience_members: dict[str, list[dict[str, str]]] = {}
    read = repeats_merged = invalid_skipped = 0

    def progress_page() -> ImportPage:
        return ImportPage(
            processed=0,
            save=lambda: SavedPage(imported=0),
            checkpoint={"key": fingerprint, "exports": json.dumps(exports), "skipped": json.dumps(skipped)},
        )

    list_counts = [audience.contact_count for audience in audiences.values() if audience.kind == "list"]
    counts = [count.get("contact_count") if isinstance(count, dict) else None, *list_counts]
    # The account's own count can lag behind its lists, and reading no contacts would empty every cohort.
    known_counts = [value for value in counts if isinstance(value, int)]
    everyone_count = max(known_counts, default=None)
    if everyone_count == 0 and len(known_counts) < len(counts):
        everyone_count = None
    for target, contact_count in (
        (ALL_CONTACTS, everyone_count),
        *[(audience.id, audience.contact_count) for audience in audiences.values()],
    ):
        audience = audiences.get(target)
        is_segment = audience is not None and audience.kind == "segment"
        if is_segment and segments_deadline is None:
            # They're prepared at the same time, so one that SendGrid never finishes holds the import up only once.
            segments_deadline = time.monotonic() + EXPORT_TIMEOUT_SECONDS
            for segment in [row for row in audiences.values() if row.kind == "segment" and row.id not in exports]:
                with suppress(_ExportUnusable):
                    exports[segment.id] = _start_export(client, segment)
            yield progress_page()
        rows: list[_Row] = []
        failure: _ExportGone | None = None
        # An export can have expired since an earlier attempt, or its download can fail, and a new one then works.
        for _ in range(2):
            try:
                if target not in exports:
                    exports[target] = _start_export(client, audience)
                    yield progress_page()
                export = _ready_export(client, exports[target], segments_deadline)
                rows = _read_rows(client, export, custom_fields)
                if audience and is_segment:
                    _check_segment_size(audience, export, len(rows), read)
                    if memberships + len(rows) > MAX_CONTACT_MEMBERSHIPS:
                        raise _ExportUnusable("It has more contacts than this import has room for.")
                else:
                    _check_export_size(export, len(rows), contact_count, read if audience else None)
                if rows and not any(exact_email(row.email) for row in rows):
                    raise _NoEmails("SendGrid's contact export holds no valid email address.")
                failure = None
                break
            except _ExportGone as e:
                failure = e
                if not isinstance(e, _ExportPending):
                    exports.pop(target, None)
                if isinstance(e, _ExportUnusable | _NoEmails):
                    break
        if failure is not None:
            # SendGrid doesn't say how it exports nothing, so a segment, or what it counts as empty, can't stop
            # the import. Contacts can have a phone number only, so a list without an email address can't either.
            may_be_empty = isinstance(failure, _ExportUnusable) and (contact_count == 0 or is_segment)
            if audience is None and may_be_empty:
                yield ImportPage(processed=0, save=lambda: SavedPage(imported=0, warnings=(NO_CONTACTS_NOTE,)))
                return
            may_be_empty = may_be_empty or (isinstance(failure, _ExportUnreadable) and contact_count == 0)
            if audience is not None and (may_be_empty or is_segment or isinstance(failure, _NoEmails)):
                del audiences[target]
                exports.pop(target, None)
                skipped[target] = _skipped_note(audience, str(failure))
                yield progress_page()
                continue
            yield progress_page()
            raise ImportProviderUnavailable(str(failure)) from failure
        # Only an export that passed every check adds people.
        members = [member for row in rows if (member := contacts.add(row.email, row.properties))]
        memberships += len(members)
        if target == ALL_CONTACTS:
            read = len(rows)
            repeats_merged, invalid_skipped = contacts.repeats_merged, contacts.invalid_skipped
        else:
            audience_members[target] = members

    # The opt-out steps read these before SendGrid prepared the exports, which can take hours. Someone who left in
    # between is in the exports, so every opt-out is read again here, and global unsubscribes stay out of the cohorts.
    for page in chain(
        _fetch_suppressions(client, context, None, fingerprint),
        _fetch_group_unsubscribes(client, context, None, fingerprint),
    ):
        yield replace(progress_page(), save=partial(_save_without_counts, page.save))
    addresses = {row["email"].lower() for row in contacts.everyone}
    unsubscribed: dict[str, list[str]] = {}
    end_time = int(timezone.now().timestamp())
    for list_page in _list_pages_after(client, "/v3/suppression/unsubscribes", 0, None, end_time):
        for entry in list_page.rows:
            address = exact_email(_list_email(entry))
            if address and address.lower() in addresses:
                unsubscribed[address] = [ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
    non_members = frozenset(address.lower() for address in unsubscribed)
    yield ImportPage(
        processed=read,
        save=partial(
            _save_contacts,
            context,
            ContactList(
                cohort_name=f"SendGrid contacts ({account.username[:MAX_SOURCE_NAME_LENGTH]})",
                cohort_description=f"Imported from SendGrid contacts of account {account.user_id}.",
                source="your SendGrid contacts",
                rows=contacts.everyone,
                non_members=non_members,
                repeats_merged=repeats_merged,
                invalid_skipped=invalid_skipped,
            ),
            [
                ContactList(
                    cohort_name=audience.cohort_name,
                    cohort_description=f"Imported from SendGrid {audience.kind} {audience.id}.",
                    source=f'the SendGrid {audience.kind} "{audience.name}"',
                    rows=tuple(audience_members[audience.id]),
                    non_members=non_members,
                )
                for audience in audiences.values()
            ],
            [*contacts.other_spellings, *unsubscribed],
            unsubscribed,
            tuple(skipped.values()),
        ),
    )


def _skipped_note(audience: "_Audience", reason: str) -> str:
    return f"{audience.name} wasn't imported, so its cohort stays as it was, with anyone who left it since. {reason}"


def _save_contacts(
    context: ImportContext,
    everyone: ContactList,
    lists: list[ContactList],
    other_spellings: list[str],
    unsubscribed: dict[str, list[str]],
    warnings: tuple[str, ...],
) -> SavedPage:
    saved = save_contact_lists(context, everyone, lists, other_spellings, unsubscribed)
    return replace(saved, warnings=(*saved.warnings, *warnings))


@frozen
class _Audience:
    kind: Literal["list", "segment"]
    id: str
    name: str
    # None when SendGrid doesn't say, or says so too late to rely on.
    contact_count: int | None
    # A segment's count, up to a day old.
    lagging_count: int | None = None

    @property
    def cohort_name(self) -> str:
        suffix = " (from SendGrid)" if self.kind == "list" else " (segment from SendGrid)"
        return f"{self.name[: min(MAX_SOURCE_NAME_LENGTH, 400 - len(suffix))]}{suffix}"


def _read_audiences(client: SendGridClient) -> Iterator[_Audience]:
    for page in client.token_pages("/v3/marketing/lists", None, 1000):
        for row in page.data:
            if isinstance(row, dict) and row.get("id"):
                count = row.get("contact_count")
                yield _Audience(
                    kind="list",
                    id=str(row["id"]),
                    name=str(row.get("name") or row["id"]),
                    contact_count=count if isinstance(count, int) else None,
                )
    # SendGrid doesn't say whether either list has the other's segments.
    segments = {
        str(row["id"]): row
        for path in ("/v3/marketing/segments", "/v3/marketing/segments/2.0")
        for row in _read_segments(client, path)
        if isinstance(row, dict) and row.get("id")
    }
    for segment_id, row in segments.items():
        # SendGrid counts a segment up to a day late, so the count can't say whether it's empty.
        count = row.get("contacts_count")
        yield _Audience(
            kind="segment",
            id=segment_id,
            name=str(row.get("name") or segment_id),
            contact_count=None,
            lagging_count=count if isinstance(count, int) else None,
        )


def _read_segments(client: SendGridClient, path: str) -> list[Any]:
    try:
        body = client.get(path)
    except SendGridAPIError as e:
        # SendGrid replaced the first version, so an account may not have it.
        if path == "/v3/marketing/segments" and e.status_code in (404, 410):
            return []
        raise
    segments = body.get("results") if isinstance(body, dict) else None
    if not isinstance(segments, list):
        raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.")
    return segments


@frozen
class _Account:
    user_id: int
    username: str


def _read_account(client: SendGridClient) -> _Account:
    """Which account or subuser the key belongs to. Each one's contacts go into a cohort of their own, so importing one
    doesn't remove another's people."""
    body = client.get("/v3/user/username")
    user_id = body.get("user_id") if isinstance(body, dict) else None
    if not isinstance(user_id, int) or isinstance(user_id, bool):
        raise SendGridAPIError("SendGrid sent an unexpected response for /v3/user/username.")
    return _Account(user_id=user_id, username=str(body.get("username") or user_id))


def _save_without_counts(save: Callable[[], SavedPage]) -> SavedPage:
    # The opt-out steps show these counts already.
    return replace(save(), imported=0, counts={})


def _read_custom_fields(client: SendGridClient) -> dict[str, str]:
    """The name of each custom field, by its lowercased ID and name. SendGrid doesn't say which one an export names its
    columns by, or in which capitals."""
    path = "/v3/marketing/field_definitions"
    body = client.get(path)
    rows = body.get("custom_fields") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise SendGridAPIError(f"SendGrid sent an unexpected response for {path}.")
    fields = [row for row in rows if isinstance(row, dict) and row.get("id") and row.get("name")]
    return {str(row[key]).lower(): str(row["name"]) for key in ("id", "name") for row in fields}


def _contact_properties(fields: Mapping[str, str | None], custom_fields: Mapping[str, str]) -> dict[str, str]:
    return {
        name if name in CONTACT_FIELDS else custom_fields.get(name.lower(), name): value
        for name, value in fields.items()
        if value and name.lower() not in _RECORD_FIELDS
    }


class _ExportGone(Exception):
    """This export can't be read anymore. Starting it again can work."""


class _ExportUnusable(_ExportGone):
    """SendGrid's answer for this export can't be what PostHog asked for."""


class _ExportUnreadable(_ExportGone):
    """An export's file isn't the CSV file PostHog asked for."""


class _NoEmails(_ExportGone):
    """None of an export's contacts has an email address."""


class _ExportPending(_ExportUnusable):
    """SendGrid is still preparing this export."""


def _start_export(client: SendGridClient, audience: _Audience | None) -> str:
    """Starts the export of an audience, or of every contact."""
    body: dict[str, Any] = {"file_type": "csv", "notifications": {"email": False}}
    if audience is not None:
        body[f"{audience.kind}_ids"] = [audience.id]
    try:
        started = client.post("/v3/marketing/contacts/exports", body)
    except SendGridAPIError as e:
        if e.status_code in (400, 404):
            raise _ExportUnusable(f"SendGrid refused to export contacts (HTTP {e.status_code}).") from e
        raise
    export_id = started.get("id") if isinstance(started, dict) else None
    if not isinstance(export_id, str) or not export_id:
        raise SendGridAPIError("SendGrid didn't start the contact export.")
    return export_id


def _check_export_size(
    export: Mapping[str, Any], exported: int, contact_count: int | None, everyone: int | None
) -> None:
    """Refuses an export that isn't the contacts SendGrid counts, because saving it would add or remove people wrongly.
    `everyone` is how many contacts the account's own export held, or None for that export itself."""
    if not exported:
        if contact_count == 0:
            return
        of = f"none of {contact_count:,} contacts" if contact_count else "no contacts"
        raise _ExportUnusable(f"SendGrid's contact export holds {of}.")
    has_own_count = isinstance(export.get("contact_count"), int)
    if contact_count is None:
        # An export of one list that holds the whole account can mean SendGrid ignored which list PostHog asked for.
        if everyone is not None and (exported >= everyone or not has_own_count):
            raise _ExportGone(
                "SendGrid doesn't count a list or its export, so PostHog can't tell if it's the right one."
            )
        return
    if everyone is None:
        # Nothing but the account's count can show that contacts on no list are missing.
        is_wrong = contact_count > 1.02 * exported + 5 or exported > 2 * contact_count + COUNT_SLACK
    else:
        is_everyone = exported >= everyone and exported > 1.1 * contact_count + 1
        # An export that counts itself is complete, so only a count far off says it's another list's.
        factor, slack = (2, COUNT_SLACK) if has_own_count else (1.1, 1)
        is_wrong = is_everyone or contact_count > factor * exported + slack or exported > factor * contact_count + slack
    if is_wrong:
        raise _ExportGone(
            f"SendGrid's contact export holds {exported:,} contacts, but SendGrid counts {contact_count:,}."
        )


@frozen
class _Row:
    email: str | None
    properties: dict[str, str]


def _read_rows(client: SendGridClient, export: Mapping[str, Any], custom_fields: Mapping[str, str]) -> list[_Row]:
    rows: list[_Row] = []
    size = 0
    for fields in _exported_contacts(client, export):
        row = _Row(email=fields.get("email"), properties=_contact_properties(fields, custom_fields))
        size += len(row.email or "") + sum(len(name) + len(value) for name, value in row.properties.items())
        if len(rows) >= MAX_CONTACT_MEMBERSHIPS or size > MAX_CONTACT_BYTES:
            raise ImportTooLarge(TOO_MANY_CONTACTS_MESSAGE)
        rows.append(row)
    return rows


def _check_segment_size(audience: _Audience, export: Mapping[str, Any], exported: int, everyone: int) -> None:
    # Only a count of zero from SendGrid says that a segment is empty.
    if not exported and export.get("contact_count") != 0:
        raise _ExportUnusable("SendGrid's contact export holds no contacts.")
    lagging = audience.lagging_count or 0
    is_everyone = exported >= everyone and exported > 1.1 * lagging + 1
    # A contact deleted since the account's own export leaves this one just below it.
    is_nearly_everyone = exported >= 0.9 * everyone and exported > 2 * lagging + COUNT_SLACK
    if is_everyone or is_nearly_everyone:
        raise _ExportUnusable("SendGrid's export of a segment holds every contact, more than SendGrid counts in it.")
    # Nothing else shows that no contact is missing.
    if export.get("contact_count") is None and (audience.lagging_count or 0) > 2 * exported + COUNT_SLACK:
        raise _ExportUnusable("SendGrid's export of a segment holds far fewer contacts than SendGrid counts in it.")


def _exported_contacts(client: SendGridClient, export: Mapping[str, Any]) -> Iterator[dict[str, str | None]]:
    """Every contact of an export. Raises when any of them is missing, because a list that came back short would remove
    people from its cohort."""
    expected, urls = export.get("contact_count"), export.get("urls") or []
    if not isinstance(urls, list) or (expected != 0 and not urls):
        raise _ExportUnusable("SendGrid sent a contact export without its contacts.")
    read = 0
    names: list[str] = []
    for url in urls:
        try:
            with client.download(str(url)) as file:
                for fields in _csv_rows(file, names):
                    read += 1
                    yield fields
        except SendGridDownloadIncomplete as e:
            raise _ExportGone(str(e)) from e
        except SendGridAPIError as e:
            # The link expires, and only a new export has a new one.
            if e.status_code in (400, 403, 404, 410):
                raise _ExportGone("SendGrid's contact export expired. PostHog asks for a new one.") from e
            raise
    if not names and urls:
        raise _ExportUnusable("SendGrid's contact export is an empty file.")
    if isinstance(expected, int) and read != expected:
        raise _ExportGone(f"SendGrid's contact export holds {read:,} contacts, but says it holds {expected:,}.")


def _ready_export(client: SendGridClient, export_id: str, deadline: float | None) -> dict[str, Any]:
    if deadline is None:
        deadline = time.monotonic() + EXPORT_TIMEOUT_SECONDS
    while True:
        try:
            export = client.get(f"/v3/marketing/contacts/exports/{quote(export_id, safe='')}")
        except SendGridAPIError as e:
            if e.status_code == 404:
                raise _ExportGone("SendGrid deleted its contact export. PostHog asks for a new one.") from e
            raise
        if not isinstance(export, dict):
            raise SendGridAPIError("SendGrid sent an unexpected response for a contact export.")
        match export.get("status"):
            case "ready":
                return export
            case "failure":
                raise _ExportUnusable(
                    f"SendGrid couldn't export your contacts: {str(export.get('message') or '')[:200]}"
                )
        if time.monotonic() > deadline:
            raise _ExportPending("SendGrid hasn't finished exporting your contacts yet. PostHog keeps checking.")
        time.sleep(EXPORT_POLL_SECONDS)


def _csv_rows(file: IO[bytes], names: list[str]) -> Iterator[dict[str, str | None]]:
    """A contact per row, with SendGrid's own fields lowercased and custom fields as the account named them. `names`
    holds the columns of the files before this one, because SendGrid doesn't say whether each file repeats them."""
    try:
        reader = csv.reader(io.TextIOWrapper(file, encoding="utf-8-sig", newline=""), strict=True)
        first = next(reader, [])
        if not first:
            return
        known = CONTACT_FIELDS | _RECORD_FIELDS
        header = [column.strip() for column in first]
        header = [name if (name := column.lower().replace(" ", "_")) in known else column for column in header]
        has_header = sorted(header) == sorted(names) if names else "email" in header
        if has_header:
            names[:] = header
        elif not names:
            raise _ExportUnreadable(UNREADABLE_EXPORT_MESSAGE)
        for row in reader if has_header else chain([first], reader):
            if not row:
                continue
            if len(row) != len(names):
                raise _ExportUnreadable(UNREADABLE_EXPORT_MESSAGE)
            # The first column with a name counts, so a custom field can't stand in for SendGrid's own.
            yield dict(zip(reversed(names), reversed(row)))
    except (csv.Error, UnicodeDecodeError) as e:
        raise _ExportUnreadable(UNREADABLE_EXPORT_MESSAGE) from e


def _fetch_senders(
    client: SendGridClient, context: ImportContext, resume: StepCheckpoint | None, fingerprint: str
) -> Iterator[ImportPage]:
    page_size = 100
    last_seen = resume.get("last_seen") if resume else None
    while True:
        params: dict[str, Any] = {"limit": page_size}
        if last_seen is not None:
            params["lastSeenID"] = last_seen
        try:
            body = client.get("/v3/verified_senders", params)
        except SendGridScopeMissing:
            # No restricted scope reads verified senders, so a key made for this import usually can't.
            yield ImportPage(processed=0, save=lambda: SavedPage(imported=0, warnings=(SENDERS_NEED_FULL_ACCESS,)))
            return
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list):
            raise SendGridAPIError("SendGrid sent an unexpected response for /v3/verified_senders.")
        more = len(results) == page_size and results[-1].get("id") not in (None, last_seen)
        last_seen = results[-1].get("id") if more else None
        yield ImportPage(
            processed=len(results),
            save=partial(_save_senders, context, results),
            checkpoint={"key": fingerprint, "last_seen": last_seen} if last_seen is not None else None,
        )
        if not more:
            return


def _save_senders(context: ImportContext, results: list[dict[str, Any]]) -> SavedPage:
    posthog_senders = _senders(context.team_id)
    counts: Counter[str] = Counter()
    items: list[ImportItem] = []
    for sender in results:
        address = str(sender.get("from_email") or "")
        integration = sender_for_address(address, posthog_senders) if address else None
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
    dns = domain.get("dns")
    if not isinstance(dns, dict):
        return []
    hosts = [str(record["host"]) for record in dns.values() if isinstance(record, dict) and record.get("host")]
    # A custom SPF record and the mail server record share a host.
    return list(dict.fromkeys(hosts))
