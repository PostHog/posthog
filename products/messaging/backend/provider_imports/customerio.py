import re
import json
import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import replace
from functools import partial
from typing import Any

from posthog.dataclasses import frozen

from products.messaging.backend.models.message_category import MessageCategory
from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.provider_import_run import ImportProviderKey
from products.messaging.backend.provider_imports.base import (
    ImportContext,
    ImportCredentials,
    ImportCredentialsConflict,
    ImportCredentialsInvalid,
    ImportCredentialsMissing,
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
    MAX_CONTACT_MEMBERSHIPS,
    ContactCollector,
    ContactList,
    new_people_page,
    new_people_step,
    save_contact_lists,
)
from products.messaging.backend.provider_imports.emails import exact_email
from products.messaging.backend.services import customerio_config
from products.messaging.backend.services.customerio_client import CustomerIOAPIError, CustomerIOClient
from products.messaging.backend.services.customerio_exports import (
    ExportedPerson,
    ExportError,
    ExportGone,
    ExportTooLarge,
    OpenExport,
    PeopleExport,
    open_people_export,
    start_people_export,
    wait_for_people_export,
)
from products.messaging.backend.services.customerio_import_service import (
    CUSTOMERIO_SUPPRESSION_TYPES,
    CustomerIOImportService,
    GlobalUnsubscribePage,
    SuppressionPage,
    topic_category_key,
    topic_name_in_preferences,
)
from products.workflows.backend.facade.people_import import MAX_SOURCE_NAME_LENGTH

logger = logging.getLogger(__name__)

SUPPRESSION_TYPE_ORDER = tuple(CUSTOMERIO_SUPPRESSION_TYPES)
# The key check runs on the request path and tries both regions, so it gets a shorter timeout than the import steps.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
CONTACTS_FLAG = "workflows-customerio-contacts-import"
CONTACT_OPT_OUT_STEPS = ("categories", "suppressions", "opt_outs")
MAX_SEGMENTS = 500
# Each membership is stored again for its segment's cohort.
MAX_SEGMENT_MEMBERSHIPS = MAX_CONTACT_MEMBERSHIPS
# Customer.io's own columns of an export. Any other column is an attribute of the workspace's people.
CUSTOMERIO_COLUMNS = frozenset({"email", "id", "cio_id", "unsubscribed", "cio_subscription_preferences"})
CUSTOMERIO_COLUMN_PREFIXES = ("_cio_", "_created_in_customerio_at", "_last_visit")
NO_EXPORT_ACCESS_MESSAGE = (
    "Customer.io doesn't let this App API key export people, which Contacts needs. Use a key that can, or leave out "
    "Contacts and New people from contacts."
)
INVALID_CREDENTIALS_MESSAGE = (
    "Customer.io rejected the App API key. Check that it is an App API key, that it has not expired, "
    "and that you copied all of it."
)


class CustomerIOImportProvider(ImportProvider):
    key = ImportProviderKey.CUSTOMERIO.value
    label = ImportProviderKey.CUSTOMERIO.label
    api_key_label = "Customer.io App API Key"
    api_key_help = "You can generate an App API key in Customer.io under Settings → Account Settings → API Credentials."
    not_imported = "Transactional messages, newsletters, forms, collections and delivery history stay in Customer.io."
    next_steps = (
        "Upload the opt-out preferences CSV, so people who left a single topic stay out of it.",
        "Import your automations from the Workflows page. They arrive as drafts.",
        "Delete people in PostHog yourself if you deleted them in Customer.io and they shouldn't get email. The import "
        "doesn't opt them out.",
        "Add your sending domain in PostHog and publish its DNS records.",
        "Run the import and upload a fresh CSV right before you stop sending from Customer.io, so late unsubscribes "
        "come over.",
    )
    steps = (
        ImportStepSpec(
            key="categories",
            label="Subscription topics",
            description="Creates a message category for each Customer.io subscription topic.",
        ),
        ImportStepSpec(
            key="suppressions",
            label="Suppressed addresses",
            description=(
                "Adds the addresses that Customer.io's email provider bounced, marked as invalid, "
                "or got a spam report for to the suppression list."
            ),
        ),
        ImportStepSpec(
            key="opt_outs",
            label="Global unsubscribes",
            description="Opts people who unsubscribed from all Customer.io messages out of all marketing messages.",
        ),
        # Needs the opt-out steps in the same run and before it, so no imported person can be sent email they left or
        # that bounced in Customer.io.
        ImportStepSpec(
            key="contacts",
            label="Contacts",
            description=(
                "Matches each person in your Customer.io workspace to a person in PostHog by email and fills in the "
                "attributes PostHog doesn't have. Fills a cohort with everyone who hasn't unsubscribed, and one for "
                "each segment with the people in it now. Opts people out of the topics they left. People without an "
                "email are skipped. Needs Subscription topics, "
                "Suppressed addresses and Global unsubscribes selected too, so no one who left in Customer.io gets "
                "marketing email."
            ),
            count_labels=(
                *CONTACT_COUNT_LABELS,
                ("no_email", "Skipped because they have no email"),
                ("unsubscribed", "Unsubscribed, not in a cohort"),
                ("topic_opt_outs", "People who left a topic"),
            ),
            requires=CONTACT_OPT_OUT_STEPS,
            requires_fresh=True,
            needs=CONTACT_OPT_OUT_STEPS,
            counts_as_events=True,
            feature_flag=CONTACTS_FLAG,
            hidden_note="People and most segments stay in Customer.io.",
        ),
        new_people_step("Customer.io", CONTACTS_FLAG),
    )

    def check_step_access(self, team_id: int, credentials: ImportCredentials, steps: list[str]) -> None:
        if "contacts" not in steps:
            return
        service = CustomerIOImportService(team_id, credentials.api_key, None)
        try:
            if service.connect(timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS) and service.client:
                service.client.get("/exports")
        except CustomerIOAPIError as e:
            if e.status_code in (401, 403):
                raise ImportCredentialsInvalid(NO_EXPORT_ACCESS_MESSAGE) from e
            raise ImportProviderUnavailable(_api_error_message(e)) from e

    def check_credentials(
        self, team_id: int, api_key: str | None, settings: Mapping[str, str], steps: Sequence[str]
    ) -> ImportCredentials:
        try:
            resolved_key = customerio_config.resolve_app_api_key(team_id, api_key)
        except customerio_config.ConfigIncomplete as e:
            raise ImportCredentialsMissing(str(e)) from e
        except customerio_config.ConfigConflict as e:
            raise ImportCredentialsConflict(str(e)) from e
        try:
            connected = CustomerIOImportService(team_id, resolved_key, None).connect(
                timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS
            )
        except CustomerIOAPIError as e:
            raise ImportProviderUnavailable(_api_error_message(e)) from e
        if not connected:
            raise ImportCredentialsInvalid(INVALID_CREDENTIALS_MESSAGE)
        return ImportCredentials(api_key=resolved_key)

    def store_credentials(self, team_id: int, credentials: ImportCredentials, created_by_id: int | None) -> int:
        return customerio_config.save_app_integration(team_id, credentials.api_key, created_by_id).id

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        try:
            match step:
                case "categories":
                    yield from self._fetch_categories(self._connect(context))
                case "suppressions":
                    yield from self._fetch_suppressions(self._connect(context), checkpoint)
                case "opt_outs":
                    yield from self._fetch_opt_outs(self._connect(context), checkpoint)
                case "contacts":
                    yield from _fetch_contacts(self._connect(context), context, checkpoint)
                case "new_people":
                    yield ImportPage(processed=0, save=new_people_page)
                case _:
                    raise UnknownImportStep(f"Customer.io has no import step named {step}.")
        except ExportTooLarge as e:
            raise ImportTooLarge(f"{e} Upload your people as a CSV file instead.") from e
        except CustomerIOAPIError as e:
            raise ImportProviderUnavailable(_api_error_message(e)) from e

    def _connect(self, context: ImportContext) -> CustomerIOImportService:
        api_key = (
            customerio_config.stored_app_api_key(context.team_id, context.integration_id)
            if context.integration_id is not None
            else None
        )
        if not api_key:
            raise ImportCredentialsMissing(
                "The Customer.io App API key was deleted. Add it again and start a new import."
            )
        service = CustomerIOImportService(context.team_id, api_key, context.created_by_id)
        if not service.connect():
            raise ImportCredentialsInvalid(INVALID_CREDENTIALS_MESSAGE)
        return service

    def _fetch_categories(self, service: CustomerIOImportService) -> Iterator[ImportPage]:
        assert service.client is not None
        topics = service.client.get_subscription_topics()
        yield ImportPage(processed=len(topics), save=partial(_save_categories, service, topics))

    def _fetch_suppressions(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        resume_type = checkpoint.get("suppression_type") if checkpoint else None
        start_index = SUPPRESSION_TYPE_ORDER.index(resume_type) if resume_type in SUPPRESSION_TYPE_ORDER else 0
        for index in range(start_index, len(SUPPRESSION_TYPE_ORDER)):
            suppression_type = SUPPRESSION_TYPE_ORDER[index]
            offset = int(checkpoint.get("offset", 0)) if checkpoint and suppression_type == resume_type else 0
            for page in service.fetch_suppression_pages(suppression_type, offset):
                next_checkpoint: StepCheckpoint | None
                if not page.is_last:
                    next_checkpoint = {"suppression_type": suppression_type, "offset": page.next_offset}
                elif index + 1 < len(SUPPRESSION_TYPE_ORDER):
                    next_checkpoint = {"suppression_type": SUPPRESSION_TYPE_ORDER[index + 1], "offset": 0}
                else:
                    next_checkpoint = None
                yield ImportPage(
                    processed=page.entries, save=partial(_save_suppressions, service, page), checkpoint=next_checkpoint
                )

    def _fetch_opt_outs(
        self, service: CustomerIOImportService, checkpoint: StepCheckpoint | None
    ) -> Iterator[ImportPage]:
        start = checkpoint.get("start") if checkpoint else None
        for page in service.fetch_global_unsubscribe_pages(start=str(start) if start else None):
            yield ImportPage(
                processed=page.customers,
                save=partial(_save_opt_outs, service, page),
                checkpoint={"start": page.next_start} if page.next_start else None,
            )


def _save_categories(service: CustomerIOImportService, topics: list[dict]) -> SavedPage:
    service.import_categories(topics)
    errors = service.progress["errors"]
    warnings = _opt_in_warnings(topics)
    if not errors:
        return SavedPage(imported=service.progress["categories_created"], warnings=warnings)
    # The service's errors hold raw exception text, which stays in the server log.
    logger.warning("Customer.io topics failed to import", extra={"team_id": service.team_id, "errors": errors})
    return SavedPage(
        imported=service.progress["categories_created"],
        warnings=(
            f"{len(errors)} subscription topics couldn't be imported. Run the import again to retry them.",
            *warnings,
        ),
    )


def _opt_in_warnings(topics: list[dict]) -> tuple[str, ...]:
    names = [str(topic.get("name")) for topic in topics if topic.get("subscribed_by_default") is False]
    if not names:
        return ()
    return (
        f"People start unsubscribed from these topics in Customer.io: {', '.join(names)}. PostHog has no opt-in "
        "categories, so anyone without an opt-out can get these messages. Send them only to a cohort of people who "
        "subscribed.",
    )


def _save_suppressions(service: CustomerIOImportService, page: SuppressionPage) -> SavedPage:
    added = service.save_suppression_page(page)
    return SavedPage(
        imported=added,
        counts=_skip_reasons(
            no_address_or_repeat=page.entries - len(page.addresses), already_suppressed=len(page.addresses) - added
        ),
    )


def _save_opt_outs(service: CustomerIOImportService, page: GlobalUnsubscribePage) -> SavedPage:
    unique_emails = len(set(page.emails))
    changed = service.save_opt_outs(list(page.emails), [ALL_MESSAGE_PREFERENCE_CATEGORY_ID]) if page.emails else 0
    return SavedPage(
        imported=changed,
        counts=_skip_reasons(
            no_email=page.customers - len(page.emails),
            duplicate_email=len(page.emails) - unique_emails,
            already_opted_out=unique_emails - changed,
        ),
    )


def _skip_reasons(**counts: int) -> dict[str, int]:
    return {reason: count for reason, count in counts.items() if count}


@frozen
class _People:
    everyone: ContactList
    segments: tuple[ContactList, ...]
    segments_left_out: tuple[str, ...]
    other_spellings: tuple[str, ...]
    opt_outs: Mapping[str, frozenset[str]]
    read: int
    no_email: int
    topic_opt_outs: int
    unreadable_preferences: int


def _fetch_contacts(
    service: CustomerIOImportService, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    """Reads a whole export before it saves, so a file that can't be read changes no cohort. The checkpoint holds the
    export Customer.io already started, so a retry reads that one rather than waiting for another."""
    assert service.client is not None
    client = service.client
    segments = _read_segments(client)
    export_id = int(checkpoint["export"]) if checkpoint and checkpoint.get("export") else None
    if export_id is None:
        export_id = start_people_export(client, [segment.id for segment in segments if not segment.problem])
        yield _progress_page(export_id)
    try:
        people = _read_people(client, context, wait_for_people_export(client, export_id), segments)
    except ExportGone as e:
        # The next try starts a new export.
        yield _progress_page(None)
        raise ImportProviderUnavailable(str(e)) from e
    yield ImportPage(processed=people.read, save=partial(_save_contacts, context, people))


def _progress_page(export_id: int | None) -> ImportPage:
    return ImportPage(processed=0, save=lambda: SavedPage(imported=0), checkpoint={"export": export_id or 0})


@frozen
class _Segment:
    id: str
    name: str
    is_manual: bool
    # Why the segment can't be imported, or an empty string.
    problem: str = ""


def _read_segments(client: CustomerIOClient) -> list[_Segment]:
    """Manual segments first, because PostHog can rebuild the others from their rules."""
    segments: list[_Segment] = []
    for row in client.get("/segments").get("segments") or []:
        if not isinstance(row, dict) or not re.fullmatch(r"[0-9]{1,18}", str(row.get("id", ""))):
            continue
        is_manual = row.get("type") == "manual"
        problem = ""
        if row.get("state", "finished") != "finished":
            problem = "Customer.io is still building it."
        segments.append(
            _Segment(
                id=str(row["id"]),
                name=str(row.get("name") or f"Segment {row['id']}").strip(),
                is_manual=is_manual,
                problem=problem,
            )
        )
    segments.sort(key=lambda segment: (bool(segment.problem), not segment.is_manual, int(segment.id)))
    return [
        segment
        if index < MAX_SEGMENTS or segment.problem
        else replace(segment, problem=f"One import takes {MAX_SEGMENTS} segments.")
        for index, segment in enumerate(segments)
    ]


def _read_people(
    client: CustomerIOClient, context: ImportContext, export: PeopleExport, segments: Sequence[_Segment]
) -> _People:
    categories = _topic_categories(client, context.team_id)
    collector = ContactCollector()
    non_members: set[str] = set()
    opt_outs: dict[str, set[str]] = {}
    members = _SegmentMembers(segments)
    read = no_email = topic_opt_outs = unreadable = 0
    with open_people_export(client, export) as file:
        for person in file.people:
            read += 1
            if not person.values.get("email", "").strip():
                no_email += 1
                continue
            choices = _choices(person)
            unreadable += choices.unreadable
            row = collector.add(person.values["email"], _properties(person))
            if row is None:
                continue
            address = exact_email(person.values["email"]) or row["email"]
            members.add(row, person.segment_ids)
            left = {categories[topic] for topic in choices.left_topics if topic in categories}
            topic_opt_outs += bool(left)
            if choices.left_everything:
                # Two people can share an address, and one of them leaving is enough.
                non_members.add(row["email"].lower())
                left.add(ALL_MESSAGE_PREFERENCE_CATEGORY_ID)
            if left:
                opt_outs.setdefault(address, set()).update(left)
        place = _place(client, file)
        segment_ids = file.segment_ids
    lists, left_out = _segment_lists(place, segments, segment_ids, members, frozenset(non_members))
    return _People(
        segments=lists,
        segments_left_out=left_out,
        everyone=ContactList(
            cohort_name=f"Customer.io people ({place})",
            cohort_description=f"Imported from Customer.io people ({place}).",
            source=f"your Customer.io people ({place})",
            rows=collector.everyone,
            non_members=frozenset(non_members),
            repeats_merged=collector.repeats_merged,
            invalid_skipped=collector.invalid_skipped,
        ),
        other_spellings=collector.other_spellings,
        opt_outs={address: frozenset(left) for address, left in opt_outs.items()},
        read=read,
        no_email=no_email,
        topic_opt_outs=topic_opt_outs,
        unreadable_preferences=unreadable,
    )


class _SegmentMembers:
    """Who is in each segment. Past the limit the last segment gives up its members, so the total stays bounded."""

    def __init__(self, segments: Sequence[_Segment]) -> None:
        self._members: dict[str, dict[int, dict[str, str]]] = {
            segment.id: {} for segment in segments if not segment.problem
        }
        self._total = 0
        self.left_out: set[str] = set()

    def add(self, row: dict[str, str], segment_ids: Iterable[str]) -> None:
        for segment_id in segment_ids:
            # Two people who share an address share a row.
            if (rows := self._members.get(segment_id)) is None or id(row) in rows:
                continue
            rows[id(row)] = row
            self._total += 1
            if self._total > MAX_SEGMENT_MEMBERSHIPS:
                last, dropped = next((key, rows) for key, rows in reversed(self._members.items()) if rows)
                del self._members[last]
                self._total -= len(dropped)
                self.left_out.add(last)

    def rows(self, segment_id: str) -> tuple[dict[str, str], ...]:
        return tuple(self._members.get(segment_id, {}).values())


def _segment_lists(
    place: str,
    segments: Sequence[_Segment],
    exported: frozenset[str],
    members: _SegmentMembers,
    non_members: frozenset[str],
) -> tuple[tuple[ContactList, ...], tuple[str, ...]]:
    """A cohort for each segment, and a note for each segment left out, whose cohort stays as it was."""
    lists: list[ContactList] = []
    left_out: list[str] = []
    for segment in segments:
        problem = segment.problem
        if not problem and segment.id not in exported:
            problem = "Customer.io's export doesn't say who is in it."
        if not problem and segment.id in members.left_out:
            problem = "The segments hold more people than one import takes."
        if problem:
            left_out.append(f'The segment "{segment.name}" wasn\'t imported. {problem}')
            continue
        lists.append(
            ContactList(
                cohort_name=f"{segment.name[:MAX_SOURCE_NAME_LENGTH]} (from Customer.io)",
                cohort_description=f"Imported from Customer.io segment {segment.id} in {place}.",
                source=f'the Customer.io segment "{segment.name}"',
                rows=members.rows(segment.id),
                empty_note="No people with an email.",
                non_members=non_members,
            )
        )
    return tuple(lists), tuple(left_out)


def _place(client: CustomerIOClient, file: OpenExport) -> str:
    region = "EU" if client.BASE_URL == CustomerIOClient.EU_BASE_URL else "US"
    return f"{region} workspace {file.workspace_id}"


@frozen
class _Choices:
    left_everything: bool
    left_topics: frozenset[str] = frozenset()
    unreadable: bool = False


def _choices(person: ExportedPerson) -> _Choices:
    left_everything = person.values.get("unsubscribed", "").strip().lower() in ("true", "1")
    raw = person.values.get("cio_subscription_preferences", "").strip()
    if not raw:
        return _Choices(left_everything=left_everything)
    try:
        preferences = json.loads(raw)
    except ValueError:
        preferences = None
    topics, channels = (
        (preferences.get("topics") or {}, preferences.get("channels") or {})
        if isinstance(preferences, dict)
        else (None, None)
    )
    if not isinstance(topics, dict) or not isinstance(channels, dict):
        # What they left can't be known, so they get no marketing email.
        return _Choices(left_everything=True, unreadable=True)
    return _Choices(
        left_everything=left_everything or _is_off(channels.get("email")),
        left_topics=frozenset(str(topic) for topic, choice in topics.items() if _is_off(choice)),
    )


def _is_off(choice: Any) -> bool:
    return choice is not None and str(choice).strip().lower() in ("false", "0")


def _topic_categories(client: CustomerIOClient, team_id: int) -> dict[str, str]:
    """The category each topic imported as, by every name a person's preferences can use for the topic. A topic whose
    category someone deleted is left out."""
    topics = client.get_subscription_topics()
    keys: dict[str, str] = {}
    # Customer.io keys a choice by `topic_<id>`, so that name wins over another topic's identifier or bare id.
    for alias in (lambda t: f"topic_{t.get('id')}", topic_name_in_preferences, lambda t: str(t.get("id"))):
        for topic in topics:
            keys.setdefault(alias(topic), topic_category_key(topic))
    categories = MessageCategory.objects.filter(team_id=team_id, key__in=set(keys.values()), deleted=False)
    ids = {key: str(category_id) for key, category_id in categories.values_list("key", "id")}
    return {name: ids[key] for name, key in keys.items() if key in ids}


def _properties(person: ExportedPerson) -> dict[str, str]:
    properties = {
        name: value
        for name, value in person.values.items()
        if name not in CUSTOMERIO_COLUMNS and not name.startswith(CUSTOMERIO_COLUMN_PREFIXES)
    }
    # PostHog matches people by email, so the ID only stays as a property.
    if customer_id := person.values.get("id", "").strip():
        properties["customerio_id"] = customer_id
    return properties


def _save_contacts(context: ImportContext, people: _People) -> SavedPage:
    saved = save_contact_lists(context, people.everyone, people.segments, people.other_spellings, people.opt_outs)
    if saved.error is not None:
        return saved
    warnings = saved.warnings
    if people.unreadable_preferences:
        warnings = (
            *warnings,
            f"Subscription preferences PostHog can't read: {people.unreadable_preferences:,}. The people they belong to "
            "are opted out of all marketing messages.",
        )
    return replace(
        saved,
        warnings=(*warnings, *people.segments_left_out),
        counts={
            **saved.counts,
            "no_email": people.no_email,
            "unsubscribed": len(people.everyone.non_members),
            "topic_opt_outs": people.topic_opt_outs,
        },
    )


def _api_error_message(error: CustomerIOAPIError) -> str:
    if isinstance(error, ExportError):
        return str(error)
    if error.status_code is None:
        return "Customer.io did not respond."
    return f"Customer.io returned HTTP {error.status_code}."
