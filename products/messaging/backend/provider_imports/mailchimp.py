"""Imports audiences, groups, cleaned contacts, abuse reports, templates, campaigns and subscribers from Mailchimp.

Mailchimp keeps contacts per audience. Each audience becomes a marketing category, and each group a recipient can pick
becomes one too. The audience steps read only who left, never subscribed, or isn't in a group. Only the contacts step
makes people, and only of contacts who are subscribed to an audience.

Steps that read contacts walk a sorted list of targets, one per audience and contact status, and page through each one
by offset. The checkpoint names the target and the offset, so a retried step continues where it stopped.
"""

import re
import html
import json
import hashlib
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import field, replace
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from django.db import transaction

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_suppression import SuppressionSource
from products.messaging.backend.models.message_template import MessageTemplate
from products.messaging.backend.models.provider_import_run import ImportProviderKey, ProviderImportRun
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
    ImportTooLarge,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.provider_imports.contacts import (
    CONTACT_COUNT_LABELS,
    ContactCollector,
    ContactList,
    new_people_page,
    new_people_step,
    save_contact_lists,
)
from products.messaging.backend.provider_imports.emails import exact_email, normalized_email
from products.messaging.backend.provider_imports.imported_senders import apply_sender
from products.messaging.backend.provider_imports.mailchimp_templates import convert_email, property_name
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
from products.workflows.backend.facade.people_import import MAX_SOURCE_NAME_LENGTH, described_static_cohorts

logger = logging.getLogger(__name__)

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
# Each audience becomes its own cohort, and the contacts step saves them all in one transaction.
MAX_AUDIENCES = 500
TOO_MANY_AUDIENCES_MESSAGE = (
    f"This account has more than {MAX_AUDIENCES} audiences, more than one import takes. Upload the audiences you need "
    "as CSV files instead."
)
ACCOUNT_NAME_LENGTH = 200
# Each tag and segment becomes a cohort too, saved in the same transaction. An account past either limit still imports
# its contacts, and the cohorts left out stay as they were.
MAX_SEGMENTS = 300
# A read that fails can take minutes, so the rest are left for the next import.
MAX_FAILED_SEGMENTS = 5
MAX_SEGMENT_MEMBERSHIPS = 250_000
# Past the first page of each audience, so a huge account can't keep the import listing tags it won't take.
MAX_EXTRA_SEGMENT_PAGES = 50
SEGMENT_NAME_LENGTH = 200
_SEGMENT_FIELDS = "segments.id,segments.name,segments.type,total_items"
UNLISTED_SEGMENTS_NOTE = (
    "Mailchimp couldn't share this audience's tags and segments, so their cohorts stay as they are. Import again."
)
STOPPED_READING_NOTE = "Mailchimp failed several reads, so PostHog stopped. Import again later."
UNREADABLE_SEGMENT_NOTE = "Mailchimp couldn't share its members, so its cohort stays as it is. Import again."
# Mailchimp calls a tag a static segment. A fuzzy segment is one Mailchimp makes for its own use.
_SEGMENT_KINDS = {"static": "tag", "saved": "segment"}
NO_AUDIENCES_NOTE = "Mailchimp returned no audiences, so no cohort changed."
ALL_DELETED_NOTE = (
    "Every audience of this account was deleted in Mailchimp, so this import takes everyone out of this cohort. The "
    "people stay in PostHog."
)
NO_AUDIENCES_ROLE_MESSAGE = (
    "Mailchimp returned no audiences, but this API key may not see all of them, so no cohort changed. Import with the "
    "API key of an owner or admin of the account."
)
NO_AUDIENCES_UNCONFIRMED_MESSAGE = (
    "Mailchimp returned no audiences, but PostHog couldn't confirm that with a second read, so no cohort changed. Import "
    "again in a few minutes."
)
DELETED_AUDIENCE_NOTE = "This audience was deleted in Mailchimp, so this import takes everyone out of its cohort. The people stay in PostHog."
NOT_EMPTIED_NOTE = (
    "This audience was deleted in Mailchimp, but PostHog couldn't empty its cohort. Import again as someone who can edit "
    "it."
)
UNCONFIRMED_AUDIENCE_MESSAGE = (
    "Mailchimp doesn't list the audience of the cohort \"{cohort}\", and PostHog couldn't confirm it was deleted, so no "
    "cohort changed. Import with the API key of an owner or admin of the account, or delete the cohorts of that audience in PostHog."
)
# Mailchimp says "Owners and Admins have full account access": https://mailchimp.com/help/manage-user-levels-in-your-account/.
# For any other role, an audience it can't see would look deleted.
_ROLES_SEEING_EVERY_AUDIENCE = frozenset({"owner", "admin"})
_AUDIENCE_COHORT = re.compile(r"audience ([^,]+)(?:, (?:tag|segment) \d+)?\.")
OPT_OUT_STEPS = ("audiences", "groups", "cleaned", "complaints")
_ADDRESS_PARTS = ("addr1", "addr2", "city", "state", "zip", "country")
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
        "Customer journeys, classic automations, signup forms, reports and Mailchimp Transactional (Mandrill) stay in "
        "Mailchimp, so rebuild what you need."
    )
    next_steps = (
        "Add your sending domain in PostHog and publish its DNS records.",
        "Open each template with notes and fix what they mention, then send yourself a test.",
        "Mailchimp fills merge tags such as *|COMPANY|* from the audience. PostHog reads *|FNAME|* and *|LNAME|* "
        "from the first_name and last_name person properties and every other tag from the property of the same "
        "name. The Contacts step fills these in from your merge fields. Send them to PostHog for people who join later.",
        "Recipients see the imported audience and group names on the email preferences page. Rename any you don't "
        "want them to see.",
        "Import once more right before you delete an audience or close your Mailchimp account. PostHog can't see who "
        "unsubscribed after that. The next import takes everyone out of a deleted audience's cohort.",
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
        # Needs the opt-out steps in the same run and before it, so no imported contact can be sent marketing email they
        # left in Mailchimp.
        ImportStepSpec(
            key="contacts",
            label="Contacts",
            description=(
                "Matches each subscribed contact to a person in PostHog by email and copies their merge fields where "
                "PostHog has no value. Fills a cohort with all your subscribed contacts and one for each audience, tag and "
                "segment. Tags and segments don't update on their own: import again to refresh their cohorts. "
                "Contacts who unsubscribed, never subscribed, were archived or were cleaned stay out. Needs Audiences, "
                "Groups, Cleaned contacts and Abuse reports selected too, so no one who left in Mailchimp gets "
                "marketing email."
            ),
            count_labels=(*CONTACT_COUNT_LABELS, ("segments_failed", "Tags and segments Mailchimp couldn't share")),
            requires=OPT_OUT_STEPS,
            needs=OPT_OUT_STEPS,
            counts_as_events=True,
        ),
        new_people_step("Mailchimp"),
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
                case "audiences" | "groups" | "cleaned" | "complaints":
                    if "contacts" in context.steps:
                        # A contact whose opt-out wasn't read could get marketing email once contacts become people.
                        pages = _opt_out_pages(step, client, context, _from_list_start(checkpoint))
                        yield from map(_whole_lists_only, pages)
                    else:
                        yield from _opt_out_pages(step, client, context, checkpoint)
                case "templates":
                    yield from _fetch_templates(client, context, checkpoint)
                case "campaigns":
                    yield from _fetch_campaigns(client, context, checkpoint)
                case "contacts":
                    with _translated_errors(LOST_ACCESS_MESSAGE, " No cohort changed."):
                        yield from _fetch_contacts(client, context)
                case "new_people":
                    yield ImportPage(processed=0, save=new_people_page)
                case _:
                    raise UnknownImportStep(f"Mailchimp has no import step named {step}.")


def _opt_out_pages(
    step: str, client: MailchimpClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
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


@contextmanager
def _translated_errors(rejected_message: str, ending: str = "") -> Iterator[None]:
    try:
        yield
    except MailchimpKeyRejected as e:
        raise ImportCredentialsInvalid(f"{rejected_message}{ending}") from e
    except MailchimpRateLimited as e:
        raise ImportProviderUnavailable(f"{RATE_LIMITED_MESSAGE}{ending}") from e
    except MailchimpAPIError as e:
        raise ImportProviderUnavailable(f"{e} Import again in a few minutes.{ending}") from e


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
    audiences = client.all("/lists", "lists", {"fields": _LIST_FIELDS}, whole=True)
    ids = {str(audience.get("id") or "") for audience in audiences}
    if "" in ids or len(ids) < len(audiences):
        raise MailchimpAPIError("Mailchimp sent an unexpected response.")
    return sorted(audiences, key=lambda audience: str(audience["id"]))


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
            # A page that ends past its own total, or brings nothing before it, can't be trusted to be the last one.
            ended_early = end > page.total or (not moved_on and offset < page.total)
            last_read = set(previous_page)
            items = [item for key, item in zip(keys, page.items) if key not in read and key not in last_read]
            read.update(keys[: max(MAX_REMEMBERED_CONTACTS - len(read), 0)])
            previous_page = keys
            yield ImportPage(
                processed=len(items),
                save=partial(save, target, items, is_first_page),
                checkpoint={"target": target.position, "offset": offset, "restarts": restarts}
                if more or ended_early
                else after_target,
            )
            is_first_page = False
            if ended_early:
                yield ImportPage(processed=0, save=partial(_changing_list, target), checkpoint=after_target)
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
        return request_offset > 0
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


def _from_list_start(checkpoint: StepCheckpoint | None) -> StepCheckpoint | None:
    """Reads the checkpoint's list again, because a retry can't see how far it moved since the last page."""
    if not checkpoint or not (checkpoint.get("offset") or checkpoint.get("restarts")):
        return checkpoint
    return {"target": checkpoint.get("target", ""), "offset": 0, "restarts": 1}


def _whole_lists_only(page: ImportPage) -> ImportPage:
    """Fails the step when an audience couldn't be read whole, instead of going on with a warning."""

    def save() -> SavedPage:
        saved = page.save()
        if saved.warnings:
            raise ImportProviderUnavailable(" ".join(saved.warnings))
        return saved

    return replace(page, save=save)


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
        # Reading its contacts reports it as missing.
        return False


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
                    f"Subscribed contacts in this audience in Mailchimp: {members}. "
                    + (
                        "The Contacts step matches them to people in PostHog."
                        if "contacts" in context.steps
                        else "To send to them, import again with Contacts selected."
                    ),
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
    for interest_category in client.all(f"/lists/{quoted(list_id)}/interest-categories", "categories", whole=True):
        category_id = str(interest_category.get("id") or "")
        if not category_id:
            continue
        # Only the sender sees hidden groups, so they sort contacts rather than hold a choice.
        if interest_category.get("type") == "hidden":
            hidden += 1
            continue
        title = _clean(interest_category.get("title"))
        path = f"/lists/{quoted(list_id)}/interest-categories/{quoted(category_id)}/interests"
        for interest in client.all(path, "interests", whole=True):
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


def _fetch_contacts(client: MailchimpClient, context: ImportContext) -> Iterator[ImportPage]:
    audiences = _audiences(client)
    if len(audiences) > MAX_AUDIENCES:
        raise ImportTooLarge(TOO_MANY_AUDIENCES_MESSAGE)
    # A project can import several accounts, and each one's import sets only its own cohort of all contacts.
    account = client.get("/", {"fields": "account_id,account_name,role"})
    account_id = _clean(account.get("account_id"))
    if not account_id:
        raise MailchimpAPIError("Mailchimp sent an unexpected response.")
    account_name = _clean(account.get("account_name")).strip() or account_id
    role = _clean(account.get("role"))
    made_by_imports = _cohorts_made_by_imports(context.team_id, account_id)
    emptied = _cohorts_of_deleted_audiences(client, made_by_imports, account_id, role, audiences)
    if not audiences:
        yield _no_audiences_page(client, context, account_id, account_name, role, made_by_imports, emptied)
        return
    # Every cohort is set to exactly what was read, so the step reads every audience before it saves, and a retry reads
    # them again.
    run_started = ProviderImportRun.objects.for_team(context.team_id).get(id=context.run_id).created_at
    contacts = ContactCollector()
    lists: list[ContactList] = []
    subscribed: list[tuple[dict[str, Any], dict[str, dict[str, str]]]] = []
    read = 0
    for audience in audiences:
        members: list[dict[str, str]] = []
        target = _member_target(
            audience,
            "subscribed",
            "members.email_address,members.status,members.merge_fields,members.timestamp_opt,members.last_changed",
        )
        for page in _read_targets(client, [target], None, partial(_collect_subscribed, contacts, members, run_started)):
            if page.checkpoint and page.checkpoint.get("restarts"):
                # Contacts collected before the list changed may have left it, so the step starts over.
                raise ImportProviderUnavailable(
                    f"{_audience_name(audience)}: this audience changed in Mailchimp while PostHog read it."
                )
            # Holds the contacts in memory. Nothing reaches PostHog until the page this step yields saves.
            _whole_lists_only(page).save()
            read += page.processed
        name = _audience_name(audience)
        subscribed.append((audience, {row["email"].lower(): row for row in members}))
        lists.append(
            ContactList(
                cohort_name=f"{name[:MAX_SOURCE_NAME_LENGTH]} (from Mailchimp)",
                cohort_description=f"{_account_prefix(account_id)}audience {audience['id']}.",
                source=f'the Mailchimp audience "{name}"',
                rows=tuple(members),
                empty_note="No subscribed contacts, so no one is in its cohort.",
            )
        )
    everyone = ContactList(
        cohort_name=f"Mailchimp contacts, {account_name[:ACCOUNT_NAME_LENGTH]}",
        cohort_description=f"{_account_prefix(account_id)}all contacts.",
        source=f'the contacts of the Mailchimp account "{account_name}"',
        rows=contacts.everyone,
        empty_note="No subscribed contacts, so no one is in its cohort.",
        repeats_merged=contacts.repeats_merged,
        invalid_skipped=contacts.invalid_skipped,
    )
    segments = _read_segments(client, account_id, subscribed)

    def save() -> SavedPage:
        saved = save_contact_lists(context, everyone, [*lists, *segments.lists, *emptied], contacts.other_spellings)
        if saved.error:
            return saved
        first, *rest = _emptied_first(saved.items, len(emptied))
        return replace(
            saved,
            items=(first, *segments.skipped, *rest),
            counts={**saved.counts, "segments_failed": segments.failed},
        )

    yield ImportPage(processed=read, save=save)


@frozen
class _Segments:
    lists: tuple[ContactList, ...]
    # Says why a tag or segment has no list. Its cohort stays as it is.
    skipped: tuple[ImportItem, ...]
    failed: int = 0


def _read_segments(
    client: MailchimpClient,
    account_id: str,
    subscribed: list[tuple[dict[str, Any], dict[str, dict[str, str]]]],
) -> _Segments:
    """A list for each tag and segment, holding only contacts the import read as subscribed to its audience."""
    lists: list[ContactList] = []
    skipped: list[ImportItem] = []
    memberships = left_out = failed = oversized = 0
    found: list[tuple[int, dict[str, Any], int]] = []
    unlisted = 0
    extra_pages = MAX_EXTRA_SEGMENT_PAGES
    for position, (audience, _rows) in enumerate(subscribed):
        if failed >= MAX_FAILED_SEGMENTS:
            unlisted += 1
            continue
        path = f"/lists/{quoted(str(audience['id']))}/segments"
        offset = 0
        listed: list[tuple[int, dict[str, Any], int]] = []
        unlisted_here = 0
        try:
            while True:
                page = client.page(path, "segments", offset, {"fields": _SEGMENT_FIELDS})
                listed += [
                    (segment["id"], segment, position)
                    for segment in page.items
                    if isinstance(segment.get("id"), int) and segment.get("type") in _SEGMENT_KINDS
                ]
                unlisted_here += _keep_oldest(listed)
                end = offset + len(page.items)
                if end > page.total or (not page.items and (offset or page.total)):
                    raise MailchimpAPIError("Mailchimp sent an unexpected response.")
                offset = end
                if offset >= page.total:
                    break
                if not extra_pages:
                    unlisted_here += page.total - offset
                    break
                extra_pages -= 1
        except (MailchimpKeyRejected, MailchimpRateLimited):
            raise
        except MailchimpAPIError:
            failed += 1
            label = f"Tags and segments in {_audience_name(audience)}"
            skipped.append(ImportItem(label=label, status="failed", notes=(UNLISTED_SEGMENTS_NOTE,)))
            continue
        found += listed
        left_out += unlisted_here + _keep_oldest(found)
    # Oldest first, so a later import of an account past the limit fills the same cohorts.
    for segment_id, segment, position in found:
        if len(lists) >= MAX_SEGMENTS or oversized >= MAX_FAILED_SEGMENTS or failed >= MAX_FAILED_SEGMENTS:
            left_out += 1
            continue
        audience, rows_by_email = subscribed[position]
        kind = _SEGMENT_KINDS[segment["type"]]
        name = _clean(segment.get("name")).strip() or str(segment_id)
        # Tags and segments of the same name can sit in one audience or in several.
        cohort_name = (
            f"{name[:SEGMENT_NAME_LENGTH]} ({kind} in {_audience_name(audience)[: SEGMENT_NAME_LENGTH - 50]}, "
            "from Mailchimp)"
        )
        rows: dict[str, dict[str, str]] = {}
        if problem := _read_segment(client, audience, segment_id, rows_by_email, rows):
            failed += 1
            skipped.append(ImportItem(label=cohort_name, status="failed", notes=(problem,)))
            continue
        if memberships + len(rows) > MAX_SEGMENT_MEMBERSHIPS:
            # Reading one only to leave it out costs requests, so a few are enough to stop.
            oversized += 1
            left_out += 1
            continue
        memberships += len(rows)
        lists.append(
            ContactList(
                cohort_name=cohort_name,
                cohort_description=f"{_account_prefix(account_id)}audience {audience['id']}, {kind} {segment_id}.",
                source=f'the Mailchimp {kind} "{name}"',
                rows=tuple(rows.values()),
                empty_note="No subscribed contacts, so no one is in its cohort.",
            )
        )
    if unlisted:
        skipped.append(
            ImportItem(
                label="Tags and segments in other audiences",
                status="skipped",
                notes=(f"{unlisted:,} more audiences weren't checked for them. {STOPPED_READING_NOTE}",),
            )
        )
    if left_out:
        note = (
            STOPPED_READING_NOTE
            if failed >= MAX_FAILED_SEGMENTS
            else "Export the ones you need from Mailchimp and upload them as CSV files."
        )
        skipped.append(
            ImportItem(
                label="More tags and segments",
                status="skipped",
                notes=(
                    f"{left_out:,} more tags and segments weren't imported, and their cohorts stay as they are. {note}",
                ),
            )
        )
    if failed:
        logger.warning("Mailchimp tags couldn't be read", extra={"failed": failed, "left_out": left_out})
    return _Segments(lists=tuple(lists), skipped=tuple(skipped), failed=failed)


def _keep_oldest(segments: list[tuple[int, dict[str, Any], int]]) -> int:
    """Keeps as many as one import can read, and returns how many it left out."""
    segments.sort(key=lambda entry: entry[0])
    left_out = len(segments[MAX_SEGMENTS + MAX_FAILED_SEGMENTS :])
    del segments[MAX_SEGMENTS + MAX_FAILED_SEGMENTS :]
    return left_out


def _read_segment(
    client: MailchimpClient,
    audience: Mapping[str, Any],
    segment_id: int,
    rows_by_email: Mapping[str, dict[str, str]],
    rows: dict[str, dict[str, str]],
) -> str:
    """Adds the segment's subscribed members to `rows`, or returns why it couldn't be read whole. One segment Mailchimp
    can't build must not keep every contact out."""
    list_id = quoted(str(audience["id"]))
    target = _Target(
        position=f"{audience['id']}/{segment_id}",
        path=f"/lists/{list_id}/segments/{segment_id}/members",
        items_key="members",
        params={"fields": "members.email_address,members.status,total_items"},
        details={"audience": audience},
    )

    def collect(_target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
        for item in items:
            email = exact_email(item.get("email_address"))
            row = rows_by_email.get(email.lower()) if email and item.get("status") == "subscribed" else None
            if row is not None:
                rows[row["email"].lower()] = row
        return SavedPage(imported=0)

    try:
        for page in _read_targets(client, [target], None, collect):
            restarted = page.checkpoint is not None and page.checkpoint.get("restarts")
            if restarted or page.save().warnings:
                return "It changed in Mailchimp while PostHog read it, so its cohort stays as it is. Import again."
    except (MailchimpKeyRejected, MailchimpRateLimited):
        raise
    except MailchimpAPIError:
        return UNREADABLE_SEGMENT_NOTE
    return ""


def _account_prefix(account_id: str) -> str:
    """Starts the description of every cohort this import makes. The account and what follows find the cohort again."""
    return f"Imported from Mailchimp account {account_id}, "


def _no_audiences_page(
    client: MailchimpClient,
    context: ImportContext,
    account_id: str,
    account_name: str,
    role: str,
    made_by_imports: Mapping[str, str],
    emptied: list[ContactList],
) -> ImportPage:
    description = f"{_account_prefix(account_id)}all contacts."
    everyone = (
        [
            ContactList(
                cohort_name=made_by_imports[description],
                cohort_description=description,
                source=f'the contacts of the Mailchimp account "{account_name}"',
                rows=(),
                empty_note=ALL_DELETED_NOTE,
            )
        ]
        if description in made_by_imports
        else []
    )
    cohorts = [*everyone, *emptied]
    if not cohorts:
        item = ImportItem(
            label=f"Mailchimp contacts, {account_name}"[:MAX_SOURCE_NAME_LENGTH],
            status="skipped",
            notes=(NO_AUDIENCES_NOTE,),
        )
        return ImportPage(processed=0, save=lambda: SavedPage(imported=0, items=(item,)))
    _confirm_no_audiences(client, role)

    def save() -> SavedPage:
        saved = save_contact_lists(context, cohorts[0], cohorts[1:])
        if saved.error:
            return replace(saved, error=f"{saved.error} No cohort changed.")
        return replace(saved, items=_as_emptied(saved.items))

    return ImportPage(processed=0, save=save)


def _confirm_no_audiences(client: MailchimpClient, role: str) -> None:
    if role.lower() not in _ROLES_SEEING_EVERY_AUDIENCE:
        raise ImportCredentialsInvalid(NO_AUDIENCES_ROLE_MESSAGE)
    try:
        again = client.get("/lists", {"fields": _LIST_FIELDS, "count": mailchimp_client.PAGE_SIZE, "offset": 0})
    except MailchimpKeyRejected:
        raise
    except MailchimpAPIError as e:
        raise ImportProviderUnavailable(NO_AUDIENCES_UNCONFIRMED_MESSAGE) from e
    total = again.get("total_items")
    if again.get("lists") != [] or type(total) is not int or total != 0:
        raise ImportProviderUnavailable(NO_AUDIENCES_UNCONFIRMED_MESSAGE)


def _emptied_first(items: tuple[ImportItem, ...], emptied: int) -> tuple[ImportItem, ...]:
    """Moves the emptied cohorts, which were saved last, before the audiences, because a run keeps only its first
    items."""
    everyone, *rest = items
    others, last = rest[: len(rest) - emptied], rest[len(rest) - emptied :]
    return (everyone, *_as_emptied(tuple(last)), *others)


def _as_emptied(items: tuple[ImportItem, ...]) -> tuple[ImportItem, ...]:
    """The items of cohorts this import empties, with the ones it couldn't empty first."""
    failed = [
        replace(item, status="failed", notes=(NOT_EMPTIED_NOTE,))
        for item in items
        if item.status == "failed" or item.url is None
    ]
    # A skipped item says it was left as it is.
    done = [replace(item, status="listed") for item in items if item.status != "failed" and item.url is not None]
    return (*failed, *done)


def _cohorts_of_deleted_audiences(
    client: MailchimpClient,
    made_by_imports: Mapping[str, str],
    account_id: str,
    role: str,
    audiences: list[dict[str, Any]],
) -> list[ContactList]:
    """The cohorts earlier imports of this account made for audiences deleted since, as empty lists.

    Fails the step for an audience that's missing for another reason, because the account's own cohort would lose its
    contacts too.
    """
    prefix = _account_prefix(account_id)
    present = {str(audience["id"]) for audience in audiences}
    deleted: set[str] = set()
    emptied: list[ContactList] = []
    for description, name in made_by_imports.items():
        match = _AUDIENCE_COHORT.fullmatch(description.removeprefix(prefix))
        if match is None or match[1] in present:
            continue
        if match[1] not in deleted:
            _confirm_deleted(client, match[1], role, UNCONFIRMED_AUDIENCE_MESSAGE.format(cohort=name))
            deleted.add(match[1])
        emptied.append(
            ContactList(
                cohort_name=name,
                cohort_description=description,
                source=f'the deleted Mailchimp audience of "{name}"',
                rows=(),
                empty_note=DELETED_AUDIENCE_NOTE,
            )
        )
    return emptied


def _cohorts_made_by_imports(team_id: int, account_id: str) -> dict[str, str]:
    """The names of the cohorts earlier imports of this account made, by description, without any deleted or given
    another description since."""
    plans = (
        ProviderImportRun.objects.for_team(team_id)
        .filter(provider=ImportProviderKey.MAILCHIMP.value)
        .values_list("progress__contacts__people_imports", flat=True)
    )
    ids = {plan["cohort_id"] for stored in plans if stored for plan in stored}
    cohorts = described_static_cohorts(team_id, _account_prefix(account_id))
    return {cohort.description: cohort.name for cohort in cohorts if cohort.id in ids}


def _confirm_deleted(client: MailchimpClient, audience_id: str, role: str, unconfirmed: str) -> None:
    if role.lower() not in _ROLES_SEEING_EVERY_AUDIENCE:
        raise ImportCredentialsInvalid(unconfirmed)
    try:
        client.get(f"/lists/{quoted(audience_id)}", {"fields": "id"})
    except MailchimpNotFound:
        return
    except MailchimpKeyRejected as e:
        if e.status_code == 403:
            raise ImportCredentialsInvalid(unconfirmed) from e
        raise
    raise ImportProviderUnavailable(unconfirmed)


def _collect_subscribed(
    contacts: ContactCollector,
    members: list[dict[str, str]],
    run_started: datetime,
    _target: _Target,
    items: list[dict[str, Any]],
    _first: bool,
) -> SavedPage:
    for item in items:
        if item.get("status") != "subscribed":
            continue
        # The opt-out steps didn't see who joined after the run started, so they wait for the next import.
        joined = _timestamp(item.get("timestamp_opt")) or _timestamp(item.get("last_changed"))
        if joined and joined > run_started:
            continue
        row = contacts.add(item.get("email_address"), _merge_properties(item.get("merge_fields")))
        if row is not None:
            members.append(row)
    return SavedPage(imported=0)


def _merge_properties(merge_fields: Any) -> dict[str, Any]:
    return {property_name(_clean(tag)): _merge_value(value) for tag, value in _as_dict(merge_fields).items()}


def _merge_value(value: Any) -> Any:
    if isinstance(value, dict):
        parts = (_clean(value.get(part)).strip() for part in _ADDRESS_PARTS)
        return ", ".join(part for part in parts if part)
    return _clean(value) if isinstance(value, str) else value


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
