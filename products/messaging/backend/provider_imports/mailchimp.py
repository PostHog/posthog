"""Imports audiences, groups, cleaned contacts, abuse reports, templates and campaigns from Mailchimp.

Mailchimp keeps contacts per audience. Each audience becomes a marketing category, and each group a recipient can pick
becomes one too. People never move: the audience steps read only who left, never subscribed, or isn't in a group.

Steps that read contacts walk a sorted list of targets, one per audience and contact status, and page through each one
by offset. The checkpoint names the target and the offset, so a retried step continues where it stopped.
"""

import html
import json
import hashlib
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.models.transactional_email_key import lock_team_keys
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentials,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
    ImportItem,
    ImportPage,
    ImportProvider,
    ImportProviderUnavailable,
    ImportSettingChoice,
    ImportSettingSpec,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.provider_imports.emails import exact_email, normalized_email
from products.messaging.backend.provider_imports.imported_senders import apply_sender
from products.messaging.backend.provider_imports.mailchimp_templates import convert_email
from products.messaging.backend.services import mailchimp_client
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    carry_opt_outs,
    code_email_keys,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.mailchimp_client import (
    MailchimpAPIError,
    MailchimpClient,
    MailchimpKeyRejected,
    MailchimpNotFound,
    MailchimpRateLimited,
    data_center,
    quoted,
)
from products.messaging.backend.services.message_templates import create_template, with_editor_design

# The key check runs on the request path, so it gets a short timeout and doesn't wait out a rate limit.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
MISSING_KEY_MESSAGE = "Enter your Mailchimp API key. PostHog doesn't keep it between imports."
EXPIRED_KEY_MESSAGE = "PostHog deleted the Mailchimp API key when this import ended. Start a new import."
NO_DATA_CENTER_MESSAGE = (
    "This doesn't look like a Mailchimp API key. A key ends with your data center, such as -us21. Copy the whole key "
    "from your Mailchimp API keys page."
)
INVALID_KEY_MESSAGE = (
    "Mailchimp rejected this API key. Check that you copied all of it and that it's still active on your Mailchimp "
    "API keys page."
)
LOST_ACCESS_MESSAGE = (
    "Mailchimp stopped accepting this API key during the import. Check it's still active and import again."
)
RATE_LIMITED_MESSAGE = "Mailchimp kept asking PostHog to slow down. Import again later."
IMPORT_TAG = "imported-from-mailchimp"
CAMPAIGNS_SETTING = "campaigns"
UNSENT_CAMPAIGNS = "unsent"
RECENT_CAMPAIGNS = "recent"
ALL_CAMPAIGNS = "all"
RECENT_DAYS = 90
UNSENT_STATUSES = frozenset({"save", "paused", "schedule"})
CATEGORY_KEY_MAX_LENGTH = 64
EMAILS_PER_PAGE = 10
MAX_LIST_RESTARTS = 3
# Bounds a worker's memory on a huge list. Past it, a restart counts the contacts it reads again twice, but skips none.
MAX_REMEMBERED_CONTACTS = 100_000
# Contacts who can't get a campaign from this audience in Mailchimp, by the count each adds to.
LEFT_STATUSES = {
    "unsubscribed": "unsubscribed",
    "pending": "never_subscribed",
    "transactional": "never_subscribed",
    "archived": "archived",
}
_MAX_NOTED_ITEMS = 5
_LIST_FIELDS = (
    "lists.id,lists.name,lists.contact,lists.permission_reminder,lists.stats.member_count,"
    "lists.stats.unsubscribe_count,lists.stats.cleaned_count,lists.stats.total_contacts,total_items"
)


@frozen
class _Target:
    """One audience list a step reads page by page. `position` sorts targets, so a checkpoint keeps its place. It goes
    into the run's JSON progress, which Postgres refuses with a NUL byte in it, so its parts join with a slash."""

    position: str
    path: str
    items_key: str
    params: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)


class MailchimpImportProvider(ImportProvider):
    key = ImportProviderKey.MAILCHIMP.value
    label = ImportProviderKey.MAILCHIMP.label
    retains_credentials = False
    feature_flag = "workflows-mailchimp-import"
    api_key_label = "Mailchimp API key"
    api_key_help = (
        "Mailchimp API keys can read and change everything in your account. PostHog only reads from it, deletes the "
        "key as soon as the import ends, and asks for it again next time."
    )
    api_key_url = "https://us1.admin.mailchimp.com/account/api/"
    not_imported = (
        "Subscribed contacts don't become people in PostHog. Customer journeys, classic automations, segments, tags, "
        "signup forms, reports and Mailchimp Transactional (Mandrill) stay in Mailchimp, so rebuild what you need."
    )
    next_steps = (
        "Add your sending domain in PostHog and publish its DNS records.",
        "Open each template with notes and fix what they mention, then send yourself a test.",
        "Mailchimp fills merge tags such as *|COMPANY|* from the audience. PostHog reads *|FNAME|* and *|LNAME|* "
        "from the first_name and last_name person properties and every other tag from the property of the same "
        "name, so send those to PostHog for your people.",
        "Recipients see the imported audience and group names on the email preferences page. Rename any you don't "
        "want them to see.",
        "Once nothing sends through Mailchimp, delete the API key you created for this import.",
    )
    settings = (
        ImportSettingSpec(
            key=CAMPAIGNS_SETTING,
            label="Campaigns",
            help="Each campaign you import becomes a draft template in PostHog. None of them send on their own.",
            choices=(
                ImportSettingChoice(value=UNSENT_CAMPAIGNS, label="Drafts, paused and scheduled campaigns"),
                ImportSettingChoice(
                    value=RECENT_CAMPAIGNS, label=f"Those, and campaigns sent in the last {RECENT_DAYS} days"
                ),
                ImportSettingChoice(value=ALL_CAMPAIGNS, label="Every campaign"),
            ),
            default=UNSENT_CAMPAIGNS,
        ),
    )
    steps = (
        ImportStepSpec(
            key="audiences",
            label="Audiences",
            description=(
                "Creates a marketing message category for each audience, and opts out the contacts who unsubscribed, "
                "never subscribed or were archived there."
            ),
            count_labels=(
                ("created", "New categories"),
                ("already_present", "Already in PostHog, left as they are"),
                ("empty_audiences", "Empty audiences, not imported"),
                ("opted_out", "People with a new opt-out"),
                ("already_opted_out", "People already opted out in PostHog, left as they are"),
                ("unsubscribed", "Unsubscribed contacts"),
                ("never_subscribed", "Contacts who never subscribed or didn't confirm"),
                ("archived", "Archived contacts"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing", "Audiences Mailchimp couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="groups",
            label="Groups",
            description=(
                "Creates a marketing message category for each group contacts can choose, and opts out subscribed "
                "contacts who didn't choose it and contacts who left the audience. A contact has left if they "
                "unsubscribed, never subscribed or were archived."
            ),
            count_labels=(
                ("created", "New categories"),
                ("already_present", "Already in PostHog, left as they are"),
                ("hidden_groups", "Hidden group categories, not imported"),
                ("opted_out", "People with a new group opt-out"),
                ("already_opted_out", "People already opted out in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing", "Audiences Mailchimp couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="cleaned",
            label="Cleaned contacts",
            description=(
                "Adds contacts Mailchimp cleaned after their address bounced to your PostHog suppression list. These "
                "block all email, as they do in Mailchimp."
            ),
            count_labels=(
                ("bounced", "Cleaned addresses, which block all email"),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing", "Audiences Mailchimp couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="complaints",
            label="Abuse reports",
            description=(
                "Adds contacts who marked a campaign as spam to your PostHog suppression list. These block marketing "
                "email only."
            ),
            count_labels=(
                ("complained", "Spam complaints, which block marketing email only"),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing", "Audiences Mailchimp couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="templates",
            label="Templates",
            description=(
                "Copies your saved templates into your PostHog library, with merge tags converted to Liquid, and notes "
                "anything to review."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
                ("no_content", "Skipped because Mailchimp doesn't share their HTML"),
                ("missing", "Mailchimp couldn't find these, skipped"),
            ),
        ),
        ImportStepSpec(
            key="campaigns",
            label="Campaigns",
            description=(
                "Copies each campaign's email into your PostHog library as a draft template, with merge tags converted "
                "to Liquid."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
                ("no_content", "Skipped because they have no content"),
                ("missing", "Mailchimp couldn't find these, skipped"),
            ),
        ),
    )

    def check_credentials(
        self, team_id: int, api_key: str | None, settings: Mapping[str, str], steps: Sequence[str]
    ) -> ImportCredentials:
        if not api_key:
            raise ImportCredentialsMissing(MISSING_KEY_MESSAGE)
        if not api_key.isascii() or data_center(api_key) is None:
            raise ImportCredentialsInvalid(NO_DATA_CENTER_MESSAGE)
        client = MailchimpClient(api_key, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
        # Every Mailchimp key reads the whole account, so one call shows whether the key works.
        with _translated_errors(INVALID_KEY_MESSAGE):
            client.get("/ping")
        return ImportCredentials(api_key=api_key)

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_KEY_MESSAGE)
        with _translated_errors(LOST_ACCESS_MESSAGE):
            client = MailchimpClient(context.api_key)
            match step:
                case "audiences":
                    yield from _fetch_audiences(client, context, checkpoint)
                case "groups":
                    yield from _fetch_groups(client, context, checkpoint)
                case "cleaned":
                    targets = [_member_target(audience, "cleaned") for audience in _audiences(client)]
                    yield from _read_targets(client, targets, checkpoint, partial(_save_cleaned, context))
                case "complaints":
                    targets = [_abuse_target(audience) for audience in _audiences(client)]
                    yield from _read_targets(client, targets, checkpoint, partial(_save_complaints, context))
                case "templates":
                    yield from _fetch_templates(client, context, checkpoint)
                case "campaigns":
                    yield from _fetch_campaigns(client, context, checkpoint)
                case _:
                    raise UnknownImportStep(f"Mailchimp has no import step named {step}.")


@contextmanager
def _translated_errors(rejected_message: str) -> Iterator[None]:
    try:
        yield
    except MailchimpKeyRejected as e:
        raise ImportCredentialsInvalid(rejected_message) from e
    except MailchimpRateLimited as e:
        raise ImportProviderUnavailable(RATE_LIMITED_MESSAGE) from e
    except MailchimpAPIError as e:
        raise ImportProviderUnavailable(f"{e} Import again in a few minutes.") from e


def _clean(value: Any) -> str:
    return str(value or "").replace("\x00", "")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _category_key(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\x00".join(parts).encode()).hexdigest()
    return f"{prefix}{digest}"[:CATEGORY_KEY_MAX_LENGTH]


def _audiences(client: MailchimpClient) -> list[dict[str, Any]]:
    return sorted(
        (audience for audience in client.all("/lists", "lists", {"fields": _LIST_FIELDS}) if audience.get("id")),
        key=lambda audience: str(audience["id"]),
    )


def _audience_name(audience: Mapping[str, Any]) -> str:
    return _clean(audience.get("name")) or str(audience.get("id"))


def _member_target(audience: Mapping[str, Any], status: str, fields: str = "", **details: Any) -> _Target:
    list_id = str(audience["id"])
    member_fields = fields or "members.email_address,members.status,members.last_changed"
    return _Target(
        position=f"{list_id}/{status}",
        path=f"/lists/{quoted(list_id)}/members",
        items_key="members",
        # Oldest change first, so a contact who changes during the import moves behind the pages still to read.
        params={
            "status": status,
            "fields": f"{member_fields},total_items",
            "sort_field": "last_changed",
            "sort_dir": "ASC",
        },
        details={"audience": audience, "status": status, **details},
    )


def _abuse_target(audience: Mapping[str, Any]) -> _Target:
    list_id = str(audience["id"])
    return _Target(
        position=list_id,
        path=f"/lists/{quoted(list_id)}/abuse-reports",
        items_key="abuse_reports",
        params={"fields": "abuse_reports.email_address,abuse_reports.date,total_items"},
        details={"audience": audience},
    )


def _read_targets(
    client: MailchimpClient,
    targets: list[_Target],
    checkpoint: StepCheckpoint | None,
    save: Callable[[_Target, list[dict[str, Any]], bool], SavedPage],
) -> Iterator[ImportPage]:
    ordered = sorted(targets, key=lambda target: target.position)
    saved = str(checkpoint.get("target", "")) if checkpoint else ""
    # A target deleted since the checkpoint moves the step on to the next one.
    remaining = [target for target in ordered if target.position >= saved]
    saved_offset = (
        int(checkpoint.get("offset", 0)) if checkpoint and remaining and remaining[0].position == saved else 0
    )
    # Contacts who left the list since the checkpoint move everyone after them forward, so a resumed list reads its
    # last page again. Saving a contact twice changes nothing.
    first_offset = max(saved_offset - mailchimp_client.PAGE_SIZE, 0)
    if not remaining:
        yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    # The audiences step reads one list per contact status, so a deleted audience is reported once.
    missing_audiences: set[str] = set()
    for index, target in enumerate(remaining):
        following = remaining[index + 1] if index + 1 < len(remaining) else None
        after_target: StepCheckpoint | None = {"target": following.position, "offset": 0} if following else None
        offset = first_offset if index == 0 else 0
        restarts = int(checkpoint.get("restarts", 0)) if checkpoint and index == 0 and target.position == saved else 0
        is_first_page = index > 0 or (saved_offset == 0 and not restarts)
        read: set[bytes] = set()
        previous_page: list[bytes] = []
        while True:
            # A contact who leaves the list or changes moves every unread contact back, so each page starts a little
            # before the last one ended and skips the contacts that page already returned.
            overlap = min(mailchimp_client.PAGE_SIZE // 10, len(previous_page))
            request_offset = max(offset - overlap, 0)
            try:
                page = client.page(target.path, target.items_key, request_offset, dict(target.params))
            except MailchimpNotFound:
                audience_id = str(target.details["audience"]["id"])
                report = audience_id not in missing_audiences
                missing_audiences.add(audience_id)
                save_missing = partial(_missing_audience, target) if report else lambda: SavedPage(imported=0)
                yield ImportPage(processed=0, save=save_missing, checkpoint=after_target)
                break
            keys = [_item_key(item) for item in page.items]
            if restarts <= MAX_LIST_RESTARTS and _moved_past_overlap(
                page, keys, previous_page, request_offset, overlap
            ):
                restarts += 1
                restarting = restarts <= MAX_LIST_RESTARTS
                if restarting:
                    offset = 0
                    previous_page = []
                yield ImportPage(
                    processed=0,
                    save=(lambda: SavedPage(imported=0)) if restarting else partial(_changing_list, target),
                    checkpoint={"target": target.position, "offset": offset, "restarts": restarts},
                )
                is_first_page = False
                if restarting:
                    continue
            end = request_offset + len(page.items)
            moved_on = end > offset
            offset = max(offset, end)
            more = moved_on and offset < page.total
            last_read = set(previous_page)
            items = [item for key, item in zip(keys, page.items) if key not in read and key not in last_read]
            read.update(keys[: max(MAX_REMEMBERED_CONTACTS - len(read), 0)])
            previous_page = keys
            yield ImportPage(
                processed=len(items),
                save=partial(save, target, items, is_first_page),
                checkpoint={"target": target.position, "offset": offset, "restarts": restarts}
                if more
                else after_target,
            )
            is_first_page = False
            if not more:
                break


def _moved_past_overlap(
    page: mailchimp_client.MailchimpPage,
    keys: list[bytes],
    previous_page: list[bytes],
    request_offset: int,
    overlap: int,
) -> bool:
    """Whether more contacts left or changed since the previous page than the overlap covers, so unread ones may sit
    before this page."""
    if not keys:
        # A list's normal end is read without an empty page, so this one shrank to before the page.
        return 0 < page.total <= request_offset
    return overlap > 0 and set(keys[:overlap]).isdisjoint(previous_page)


def _item_key(item: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).digest()


def _changing_list(target: _Target) -> SavedPage:
    name = _audience_name(target.details["audience"])
    return SavedPage(
        imported=0,
        warnings=(
            f"{name}: this audience kept changing in Mailchimp during the import, so some contacts may be missing. "
            "Import again when it changes less.",
        ),
    )


def _missing_audience(target: _Target) -> SavedPage:
    name = _audience_name(target.details.get("audience") or {})
    return SavedPage(
        imported=0,
        counts={"missing": 1},
        warnings=(f"{name}: Mailchimp couldn't find this audience, so nothing imported from it. Import again.",),
    )


def _audience_category(audience: Mapping[str, Any]) -> ImportedCategory:
    name = _audience_name(audience)
    return ImportedCategory(
        key=_category_key("mailchimp_audience_", str(audience["id"])),
        name=name[:128],
        description=f"Imported from the Mailchimp audience {name}.",
        public_description="",
    )


def _is_empty(client: MailchimpClient, audience: Mapping[str, Any]) -> bool:
    stats = _as_dict(audience.get("stats"))
    counts = ("total_contacts", "member_count", "unsubscribe_count", "cleaned_count")
    if any(int(stats.get(count) or 0) for count in counts):
        return False
    # The audience stats leave out pending and archived contacts, so an audience of only those looks empty.
    path = f"/lists/{quoted(str(audience['id']))}/members"
    try:
        return not any(
            client.page(path, "members", 0, {"status": status, "fields": "total_items"}).total
            for status in ("pending", "archived")
        )
    except MailchimpNotFound:
        return True


def _fetch_audiences(
    client: MailchimpClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    audiences = _audiences(client)
    empty_ids = {str(audience["id"]) for audience in audiences if _is_empty(client, audience)}
    empty = [audience for audience in audiences if str(audience["id"]) in empty_ids]
    if empty and not checkpoint:
        names = ", ".join(_audience_name(audience) for audience in empty[:_MAX_NOTED_ITEMS])
        yield ImportPage(
            processed=0,
            save=lambda: SavedPage(
                imported=0,
                counts={"empty_audiences": len(empty)},
                items=(
                    ImportItem(
                        label="Empty audiences",
                        status="skipped",
                        notes=(f"These audiences have no contacts, so they didn't become categories: {names}.",),
                    ),
                ),
            ),
            checkpoint={"target": "", "offset": 0},
        )
    statuses = sorted(LEFT_STATUSES)
    targets = [
        _member_target(audience, status, first=status == statuses[0])
        for audience in audiences
        if str(audience["id"]) not in empty_ids
        for status in statuses
    ]
    yield from _read_targets(client, targets, checkpoint, partial(_save_left_members, context))


def _save_left_members(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    audience = target.details["audience"]
    category = _audience_category(audience)
    result = import_categories(context.team_id, [category], context.created_by_id)
    category_id = result.ids_by_key.get(category.key)
    left: dict[str, list[str]] = {}
    invalid = 0
    for item in items:
        email = exact_email(item.get("email_address"))
        if email is None:
            invalid += 1
            continue
        left[email] = [category_id] if category_id else []
    changed = import_opt_outs(context.team_id, left, context.created_by_id)
    _carry_to_every_spelling(context, left)
    counts: dict[str, int] = {
        "opted_out": changed,
        "already_opted_out": sum(1 for categories in left.values() if categories) - changed,
        LEFT_STATUSES[target.details["status"]]: len(left),
        "invalid": invalid,
    }
    items_out: tuple[ImportItem, ...] = ()
    if first and target.details.get("first"):
        stats = _as_dict(audience.get("stats"))
        members = int(stats.get("member_count") or 0)
        counts |= {"created": result.created, "already_present": result.already_present}
        items_out = (
            ImportItem(
                label=_audience_name(audience),
                status="created" if result.created else "skipped",
                url="/workflows/opt-outs",
                notes=(
                    f"Subscribed contacts in this audience in Mailchimp: {members}. PostHog doesn't create people from "
                    "an audience, and their merge fields stay in Mailchimp too. To send to them, build a cohort from "
                    "your own data or send people's details to PostHog first.",
                ),
            ),
        )
    return SavedPage(imported=changed, counts=counts, items=items_out)


@frozen
class _Group:
    id: str
    name: str
    title: str
    category: ImportedCategory


def _groups(client: MailchimpClient, audience: Mapping[str, Any]) -> tuple[list[_Group], int]:
    """The groups contacts can choose in an audience, and how many hidden group categories it has."""
    list_id = str(audience["id"])
    groups: list[_Group] = []
    hidden = 0
    for interest_category in client.all(f"/lists/{quoted(list_id)}/interest-categories", "categories"):
        category_id = str(interest_category.get("id") or "")
        if not category_id:
            continue
        # Only the sender sees hidden groups, so they sort contacts rather than hold a choice.
        if interest_category.get("type") == "hidden":
            hidden += 1
            continue
        title = _clean(interest_category.get("title"))
        path = f"/lists/{quoted(list_id)}/interest-categories/{quoted(category_id)}/interests"
        for interest in client.all(path, "interests"):
            interest_id = str(interest.get("id") or "")
            if not interest_id:
                continue
            name = _clean(interest.get("name")) or interest_id
            groups.append(
                _Group(
                    id=interest_id,
                    name=name,
                    title=title,
                    category=ImportedCategory(
                        key=_category_key("mailchimp_group_", list_id, interest_id),
                        name=name[:128],
                        description=(
                            f"Imported from Mailchimp: the {name} group under {title} in the "
                            f"{_audience_name(audience)} audience."
                        ),
                        public_description="",
                    ),
                )
            )
    return groups, hidden


def _fetch_groups(
    client: MailchimpClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    targets: list[_Target] = []
    hidden = 0
    statuses = sorted({*LEFT_STATUSES, "subscribed"})
    for audience in _audiences(client):
        groups, audience_hidden = _groups(client, audience)
        hidden += audience_hidden
        if groups:
            targets.extend(
                _member_target(
                    audience,
                    status,
                    "members.email_address,members.interests,members.last_changed" if status == "subscribed" else "",
                    groups=tuple(groups),
                    first=status == statuses[0],
                )
                for status in statuses
            )
    if hidden and not checkpoint:
        yield ImportPage(
            processed=0,
            save=lambda: SavedPage(imported=0, counts={"hidden_groups": hidden}),
            checkpoint={"target": "", "offset": 0},
        )
    yield from _read_targets(client, targets, checkpoint, partial(_save_group_members, context))


def _save_group_members(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    groups: tuple[_Group, ...] = target.details["groups"]
    left = target.details["status"] in LEFT_STATUSES
    result = import_categories(context.team_id, [group.category for group in groups], context.created_by_id)
    opt_outs: dict[str, list[str]] = {}
    invalid = 0
    for item in items:
        email = exact_email(item.get("email_address"))
        if email is None:
            invalid += 1
            continue
        interests = _as_dict(item.get("interests"))
        # Mailchimp sends a campaign for a group only to contacts who chose it, so the rest opt out of its category.
        # A group missing from the contact's answers says nothing, so it leaves them as they are. A contact who left
        # the audience gets none of its campaigns, so they opt out of every group.
        opt_outs[email] = [
            result.ids_by_key[group.category.key]
            for group in groups
            if (left or interests.get(group.id) is False) and group.category.key in result.ids_by_key
        ]
    changed = import_opt_outs(context.team_id, opt_outs, context.created_by_id)
    _carry_to_every_spelling(context, [email for email, categories in opt_outs.items() if categories])
    counts: dict[str, int] = {
        "opted_out": changed,
        "already_opted_out": sum(1 for categories in opt_outs.values() if categories) - changed,
        "invalid": invalid,
    }
    items_out: tuple[ImportItem, ...] = ()
    if first and target.details.get("first"):
        counts |= {"created": result.created, "already_present": result.already_present}
        audience = _audience_name(target.details["audience"])
        names = ", ".join(group.name for group in groups[:_MAX_NOTED_ITEMS])
        more = f" and {len(groups) - _MAX_NOTED_ITEMS} more" if len(groups) > _MAX_NOTED_ITEMS else ""
        items_out = (
            ImportItem(
                label=f"Groups in {audience}",
                status="created" if result.created else "skipped",
                url="/workflows/opt-outs",
                notes=(
                    f"Groups: {names}{more}.",
                    "Existing contacts keep their Mailchimp choices. People added later get each category by default, "
                    "until they opt out.",
                ),
            ),
        )
    return SavedPage(imported=changed, counts=counts, items=items_out)


def _carry_to_every_spelling(context: ImportContext, addresses: Iterable[str]) -> None:
    # A send matches an opt-out by exact address, and Mailchimp keeps the case the address arrived in.
    carry_opt_outs(
        context.team_id,
        [spelling for address in addresses for spelling in (address, address.lower())],
        context.created_by_id,
    )


def _save_cleaned(context: ImportContext, target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
    name = _audience_name(target.details["audience"])
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for item in items:
        email = normalized_email(item.get("email_address"))
        if email is None:
            invalid += 1
            continue
        imported[email] = ImportedSuppression(
            identifier=email,
            source=SuppressionSource.BOUNCE,
            reason=f"Imported from Mailchimp (cleaned from the {name} audience)",
            suppressed_at=_timestamp(item.get("last_changed")),
        )
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
    return SavedPage(
        imported=result.total_added,
        counts={
            "bounced": result.added.get(SuppressionSource.BOUNCE, 0),
            "already_present": result.already_present,
            "invalid": invalid,
        },
    )


def _save_complaints(context: ImportContext, target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
    name = _audience_name(target.details["audience"])
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for item in items:
        email = normalized_email(item.get("email_address"))
        if email is None:
            invalid += 1
            continue
        imported[email] = ImportedSuppression(
            identifier=email,
            source=SuppressionSource.COMPLAINT,
            reason=f"Imported from Mailchimp (abuse report in the {name} audience)",
            suppressed_at=_timestamp(item.get("date")),
        )
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
    return SavedPage(
        imported=result.total_added,
        counts={
            "complained": result.added.get(SuppressionSource.COMPLAINT, 0),
            "already_present": result.already_present,
            "invalid": invalid,
        },
    )


@frozen
class _Email:
    """One template or campaign to import, read from Mailchimp but not yet converted."""

    key: str
    label: str
    subject: str = ""
    html: str = ""
    text: str = ""
    fixed: Mapping[str, str | None] = field(default_factory=dict)
    from_name: str = ""
    from_email: str = ""
    description: str = ""
    # A saved template has no subject in Mailchimp, so it gets no note about one.
    has_subject: bool = True
    # Why there's nothing to import, when there isn't.
    skipped: str = ""
    missing: bool = False


def _audience_tags(audience: Mapping[str, Any] | None) -> dict[str, str]:
    """Merge tags with one value for everyone in an audience, filled at import so the footer keeps its address."""
    if not audience:
        return {}
    contact = _as_dict(audience.get("contact"))
    address_parts = [
        _clean(contact.get(part)) for part in ("company", "address1", "address2", "city", "state", "zip", "country")
    ]
    address = ", ".join(part for part in address_parts if part)
    tags = {
        "LIST:NAME": _audience_name(audience),
        "LIST:COMPANY": _clean(contact.get("company")),
        "LIST:DESCRIPTION": _clean(audience.get("permission_reminder")),
        "LIST:ADDRESS": address,
        "LIST:ADDRESSLINE": address,
        "HTML:LIST_ADDRESS_HTML": address,
        "LIST_ADDRESS_HTML": address,
    }
    return {tag: value for tag, value in tags.items() if value}


def _paged_emails(
    keys: list[str], read: Callable[[str], _Email], context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    after = str(checkpoint.get("after", "")) if checkpoint else ""
    remaining = [key for key in sorted(keys) if key > after]
    if not remaining:
        yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    for start in range(0, len(remaining), EMAILS_PER_PAGE):
        chunk = remaining[start : start + EMAILS_PER_PAGE]
        emails = [read(key) for key in chunk]
        is_last = start + EMAILS_PER_PAGE >= len(remaining)
        yield ImportPage(
            processed=len(chunk),
            save=partial(_save_emails, context, emails),
            checkpoint=None if is_last else {"after": chunk[-1]},
        )


def _template_sort_key(template_id: int) -> str:
    # Zero-padded, so ids sort as numbers in the checkpoint.
    return f"{template_id:020d}"


def _fetch_templates(
    client: MailchimpClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    templates = client.all(
        "/templates",
        "templates",
        {"type": "user", "fields": "templates.id,templates.name,templates.type,templates.drag_and_drop,total_items"},
    )
    by_key = {
        _template_sort_key(int(template["id"])): template
        for template in templates
        if isinstance(template.get("id"), int) and template.get("type", "user") == "user"
    }
    audiences = _audiences(client) if by_key else []
    # A saved template belongs to no audience. With only one, its footer tags can only mean that audience.
    fixed = _audience_tags(audiences[0]) if len(audiences) == 1 else {}
    yield from _paged_emails(list(by_key), lambda key: _read_template(client, by_key[key], fixed), context, checkpoint)


def _read_template(client: MailchimpClient, template: Mapping[str, Any], fixed: Mapping[str, str]) -> _Email:
    template_id = int(template["id"])
    key = f"mailchimp-template-{template_id}"
    label = (_clean(template.get("name")) or f"Template {template_id}")[:400]
    try:
        content = client.get(f"/templates/{template_id}/default-content")
    except MailchimpNotFound:
        return _Email(key=key, label=label, missing=True)
    body = content.get("html")
    if not isinstance(body, str) or not body.strip():
        return _Email(
            key=key,
            label=label,
            skipped=(
                "Mailchimp's API doesn't share this template's HTML. In Mailchimp, export the template as HTML, then "
                "paste it into a new PostHog template."
            ),
        )
    return _Email(
        key=key,
        label=label,
        html=body,
        # A saved template has no preview text, so a condition on it is false.
        fixed={**fixed, "MC_PREVIEW_TEXT": ""},
        description="Imported from Mailchimp.",
        has_subject=False,
    )


def _campaign_selected(campaign: Mapping[str, Any], choice: str, now: datetime) -> bool:
    status = campaign.get("status")
    if status in UNSENT_STATUSES or choice == ALL_CAMPAIGNS:
        return True
    if choice != RECENT_CAMPAIGNS:
        return False
    sent = _timestamp(campaign.get("send_time"))
    return sent is not None and sent >= now - timedelta(days=RECENT_DAYS)


def _fetch_campaigns(
    client: MailchimpClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    choice = context.settings.get(CAMPAIGNS_SETTING) or UNSENT_CAMPAIGNS
    now = datetime.now(UTC)
    params = {
        "fields": (
            "campaigns.id,campaigns.type,campaigns.status,campaigns.create_time,campaigns.send_time,"
            "campaigns.settings,campaigns.variate_settings.subject_lines,campaigns.recipients.list_id,total_items"
        ),
        "sort_field": "create_time",
        "sort_dir": "ASC",
    }
    # Mailchimp filters by one status at a time, so a years-long archive of sent campaigns isn't read for nothing.
    filters: list[dict[str, str]] = [{}]
    if choice != ALL_CAMPAIGNS:
        filters = [{"status": status} for status in sorted(UNSENT_STATUSES)]
    if choice == RECENT_CAMPAIGNS:
        since = (now - timedelta(days=RECENT_DAYS)).isoformat()
        filters.append({"status": "sent", "since_send_time": since})
    campaigns = [campaign for extra in filters for campaign in client.all("/campaigns", "campaigns", params | extra)]
    by_key = {
        f"{_clean(campaign.get('create_time'))}/{campaign['id']}": campaign
        for campaign in campaigns
        if campaign.get("id") and _campaign_selected(campaign, choice, now)
    }
    audiences = {str(audience["id"]): audience for audience in _audiences(client)} if by_key else {}
    yield from _paged_emails(
        list(by_key), lambda key: _read_campaign(client, by_key[key], audiences), context, checkpoint
    )


def _read_campaign(
    client: MailchimpClient, campaign: Mapping[str, Any], audiences: Mapping[str, Mapping[str, Any]]
) -> _Email:
    campaign_id = str(campaign["id"])
    settings = _as_dict(campaign.get("settings"))
    subject = _clean(settings.get("subject_line"))
    preview = _clean(settings.get("preview_text"))
    key = f"mailchimp-campaign-{campaign_id}"
    label = (_clean(settings.get("title")) or subject or f"Campaign {campaign_id}")[:400]
    try:
        content = client.get(
            f"/campaigns/{quoted(campaign_id)}/content", {"fields": "html,plain_text,variate_contents"}
        )
    except MailchimpNotFound:
        return _Email(key=key, label=label, missing=True)
    body = _clean(content.get("html"))
    text = _clean(content.get("plain_text"))
    variants = [_as_dict(variant) for variant in content.get("variate_contents") or []]
    extra_notes: list[str] = []
    subject_lines = [
        line
        for line in (_clean(line) for line in _as_dict(campaign.get("variate_settings")).get("subject_lines") or [])
        if line
    ]
    if not subject and subject_lines:
        # A subject line A/B test keeps its subjects here and leaves the campaign's own subject empty.
        subject = subject_lines[0]
        if len(subject_lines) > 1:
            extra_notes.append(
                f"This campaign tests {len(subject_lines)} subject lines in Mailchimp. PostHog used the first one."
            )
    if not body.strip() and not text.strip() and variants:
        # An A/B test keeps its content per variation, and a template holds one email.
        body, text = _clean(variants[0].get("html")), _clean(variants[0].get("plain_text"))
        if len(variants) > 1:
            label_text = _clean(variants[0].get("content_label")) or "the first one"
            extra_notes.append(
                f"This campaign is an A/B test with {len(variants)} variations. PostHog imported {label_text}."
            )
    if not body.strip() and text.strip():
        # A plain-text campaign has no HTML, so the text becomes a simple HTML body the editor can open.
        body = html.escape(text).replace("\n", "<br>\n")
    if not body.strip():
        return _Email(key=key, label=label, skipped="This campaign has no content in Mailchimp.")
    audience = audiences.get(str(_as_dict(campaign.get("recipients")).get("list_id") or ""))
    fixed: dict[str, str | None] = {**_audience_tags(audience)}
    # Text with merge tags would land in the body unconverted, so its tag stays as written for a person to fix.
    if subject and "*|" not in subject:
        fixed["MC:SUBJECT"] = subject
    # An empty preview text is still known, so a condition on it is false. One with merge tags isn't empty, so a
    # condition on it is true while the tag itself stays as written.
    fixed["MC_PREVIEW_TEXT"] = None if "*|" in preview else preview
    status = _clean(campaign.get("status"))
    sent_at = _timestamp(campaign.get("send_time"))
    sent = f" Mailchimp sent it on {sent_at.date().isoformat()}." if status == "sent" and sent_at else ""
    return _Email(
        key=key,
        label=label,
        subject=subject,
        html=body,
        text=text,
        fixed=fixed,
        from_name=_clean(settings.get("from_name")),
        from_email=_clean(settings.get("reply_to")),
        description=" ".join((f"Imported from the Mailchimp campaign {label}.{sent}", *extra_notes)),
    )


@frozen
class _PendingTemplate:
    position: int
    label: str
    key: str
    fields: dict[str, Any]
    notes: tuple[str, ...]


def _save_emails(context: ImportContext, emails: list[_Email]) -> SavedPage:
    senders = _senders(context.team_id)
    keys = [email.key for email in emails]
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = set(
        MessageTemplate.objects.filter(team_id=context.team_id, key__in=keys).values_list("key", flat=True)
    ) | code_email_keys(context.team_id, keys)
    items: list[ImportItem] = []
    pending: list[_PendingTemplate] = []
    counts: Counter[str] = Counter()
    for source in emails:
        if source.missing:
            counts["missing"] += 1
            items.append(ImportItem(label=source.label, status="failed", notes=("Mailchimp couldn't find this.",)))
            continue
        if source.key in taken:
            counts["already_present"] += 1
            items.append(
                ImportItem(
                    label=source.label,
                    status="skipped",
                    notes=(
                        f"A template with the key {source.key} is already in PostHog, or was deleted there, so it "
                        "stays as it is.",
                    ),
                )
            )
            continue
        if source.skipped:
            counts["no_content"] += 1
            items.append(ImportItem(label=source.label, status="skipped", notes=(source.skipped,)))
            continue
        taken.add(source.key)
        converted = convert_email(
            source.subject, source.html, source.text, source.fixed, expects_subject=source.has_subject
        )
        email: dict[str, Any] = with_editor_design({"subject": converted.subject, "html": converted.html})
        if converted.text:
            email["text"] = converted.text
        sender_notes: tuple[str, ...] = ()
        if source.from_email:
            sender_notes = apply_sender(email, source.from_name, source.from_email, senders)
        notes = (*converted.notes, *converted.send_notes, *sender_notes)
        fields = {
            "name": source.label,
            "key": source.key,
            # The library renders the description as Markdown, which would read `*|FNAME|*` as italics.
            "description": " ".join(part for part in (source.description, *notes) if part).replace("*", "\\*"),
            "type": "email",
            "content": {"templating": "liquid", "email": email},
            "tags": [IMPORT_TAG],
        }
        pending.append(
            _PendingTemplate(position=len(items), label=source.label, key=source.key, fields=fields, notes=notes)
        )
        items.append(ImportItem(label=source.label, status="created"))
    if pending:
        # Converting happens before the lock, so a send adding a code email key waits only for the inserts. Under it,
        # a key a send added since the check above wins.
        with transaction.atomic():
            lock_team_keys(context.team_id)
            code_keys = code_email_keys(context.team_id, [entry.key for entry in pending])
            for entry in pending:
                if entry.key in code_keys:
                    counts["already_present"] += 1
                    items[entry.position] = ImportItem(
                        label=entry.label,
                        status="skipped",
                        notes=(f"A code email sends under the key {entry.key}, so this template wasn't imported.",),
                    )
                    continue
                created = create_template(context.team_id, context.created_by_id, entry.fields)
                counts["needs_review" if entry.notes else "created"] += 1
                items[entry.position] = ImportItem(
                    label=entry.label,
                    status="created",
                    url=f"/workflows/library/templates/{created.id}",
                    notes=entry.notes,
                )
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _senders(team_id: int) -> dict[str, IntegrationRecord]:
    return {
        str(sender.config.get("email", "")).lower(): sender
        for sender in IntegrationManager.email.credentials.list(team_id)
    }
