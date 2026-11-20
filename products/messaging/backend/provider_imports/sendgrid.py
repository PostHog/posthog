"""Imports suppressions, unsubscribe groups and templates from SendGrid, and lists what can't move.

SendGrid is the one provider here with read-only scopes, so the customer can hand over a narrow key. The run still only
keeps it until it ends. SendGrid documents only stats for its automations, so they stay behind. Contacts don't become
people. A send to any address reads the blocking rules this import fills, so PostHog doesn't need them.
"""

import hashlib
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.message_suppression import SuppressionSource
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
from products.messaging.backend.provider_imports.emails import exact_email, normalized_email
from products.messaging.backend.provider_imports.senders import sender_for_address
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    carry_opt_outs,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.sendgrid_client import (
    SUPPRESSION_PAGE_SIZE,
    SendGridAPIError,
    SendGridClient,
    SendGridKeyRejected,
    SendGridRateLimited,
    SendGridResponseTooLarge,
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
MAIL_FROM_DEFAULT = "feedback"
OPT_OUT_PAGE_SIZE = 500

# A step's scopes, as SendGrid enforces them. A tuple means any one of them is enough. SendGrid refuses the suppression
# lists and group members to a key with only the per-list scopes its docs name, so these need suppression.read. Verified
# senders are missing because no restricted scope reads them, so a key that can't read those fails on the step itself
# with a message naming it.
STEP_SCOPES: dict[str, tuple[tuple[str, ...], ...]] = {
    "suppression_groups": (("asm.groups.read",),),
    "suppressions": (("suppression.read",),),
    "global_unsubscribes": (("suppression.read",),),
    "group_unsubscribes": (("asm.groups.read",), ("suppression.read",)),
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
        "stats, send history and templates stay in SendGrid."
    )
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so this "
        "needs new records. Leave your SendGrid records in place, because both tools can sign mail for one domain "
        "while you move.",
        "Rebuild your SendGrid templates and automations in PostHog, and turn each automation off in SendGrid when "
        "its workflow goes live.",
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
            count_labels=(("opted_out", "People with a new opt-out"), ("invalid", "Skipped, address isn't valid")),
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


SENDERS_NEED_FULL_ACCESS = (
    "Only a full access SendGrid key can read your verified senders, so they weren't listed. Add the addresses you "
    "send from as senders in PostHog."
)


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
                notes=(f"{row.get('contact_count') or 0} contacts. Rebuild this list as a cohort of your users.",),
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
