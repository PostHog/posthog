"""Imports suppressions, mailing list opt-outs, templates and the domain list from Mailgun.

Mailgun keeps suppressions, mailing lists and templates per region and mostly per domain, while PostHog keeps them per
team. So every step walks a sorted list of targets (a domain, a list, or an account's templates) and its checkpoint
names the target and the page inside it. Merging domains can only block more email than Mailgun does, never less.

Mailgun's API has no automations, so nothing here makes a workflow. People never move: list steps read only who left.
"""

import re
import hashlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import field
from datetime import datetime
from email.utils import parseaddr, parsedate_to_datetime
from functools import partial
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.helpers.email_utils import email_domain
from posthog.integrations import IntegrationManager, IntegrationRecord

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
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
    ImportSettingChoice,
    ImportSettingSpec,
    ImportStepSpec,
    SavedPage,
    StepCheckpoint,
    UnknownImportStep,
)
from products.messaging.backend.provider_imports.mailgun_templates import ConvertedVersion, convert_version
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.mailgun_client import (
    SUPPRESSION_PAGE_SIZE,
    TEMPLATE_PAGE_SIZE,
    MailgunAPIError,
    MailgunClient,
    MailgunKeyRejected,
    MailgunNotFound,
    MailgunRateLimited,
    MailgunRegion,
    quoted,
)
from products.messaging.backend.services.message_templates import create_template

# The key check runs on the request path, so it gets a short timeout and doesn't wait out a rate limit.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
MISSING_KEY_MESSAGE = "Enter your Mailgun API key. PostHog doesn't keep it between imports."
EXPIRED_KEY_MESSAGE = "PostHog deleted the Mailgun API key when this import ended. Start a new import."
INVALID_KEY_MESSAGE = (
    "Mailgun rejected this API key. A domain sending key can't read your data, so use an account API key from your "
    "Mailgun API keys page. Check that you copied all of it and that it's still active."
)
CANNOT_READ_MESSAGE = (
    "This Mailgun API key can't read {what}. Its role is probably Analyst, which has no access to suppressions. Use "
    "a key with the Support, Developer or Admin role, or leave {what} out of this import."
)
LOST_ACCESS_MESSAGE = (
    "Mailgun stopped accepting this API key during the import. Check it's still active and import again."
)
RATE_LIMITED_MESSAGE = "Mailgun kept asking PostHog to slow down. Import again later."
IMPORT_TAG = "imported-from-mailgun"
COMPLAINT_REASON_PREFIX = "Imported from Mailgun (spam complaint on "
REGION_SETTING = "region"
VERSIONS_SETTING = "template_versions"
ALL_REGIONS = "both"
ALL_VERSIONS = "all"
ACTIVE_VERSION = "active"
ALL_TAGS = "*"
# The label PostHog uses for a sender's MAIL FROM subdomain unless the person picks another.
MAIL_FROM_DEFAULT = "feedback"
TEMPLATE_KEY_MAX_LENGTH = 400
_MAX_KEY_NAME_LENGTH = 150
CATEGORY_KEY_MAX_LENGTH = 64
_UNSAFE_IN_KEY = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_NOTED_ITEMS = 5
_STEPS_NEEDING_SUPPRESSION_ROLE = {step: step for step in ("bounces", "complaints", "unsubscribes")}


@frozen
class _Target:
    """One thing a step reads page by page. Fields sort in this order, so a checkpoint keeps its place between runs."""

    region: MailgunRegion
    # The subaccount that owns it, or "" for the main account.
    owner: str
    name: str
    path: str
    params: Mapping[str, Any] = field(default_factory=dict)
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def position(self) -> tuple[str, str, str]:
        return (self.region.value, self.owner, self.name)

    @property
    def on_behalf_of(self) -> str | None:
        return self.owner or None


class MailgunImportProvider(ImportProvider):
    key = ImportProviderKey.MAILGUN.value
    label = ImportProviderKey.MAILGUN.label
    retains_credentials = False
    resumes_after_failure = True
    feature_flag = "workflows-mailgun-import"
    api_key_label = "Mailgun API key"
    api_key_help = (
        "Use an account API key. A domain sending key can't read your data. If your plan has key roles, choose "
        "Support: it's the smallest role that can read everything here, though Mailgun also lets it make changes. "
        "PostHog only reads from your account, deletes the key as soon as the import ends, and asks for it again next "
        "time."
    )
    api_key_url = "https://app.mailgun.com/settings/api_security"
    not_imported = (
        "Mailgun has no automations to import. Subscribed list members don't become people in PostHog. Routes, "
        "webhooks, tracking settings, send history and stats stay in Mailgun, and Mailjet is a separate product, so "
        "rebuild what you need."
    )
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so "
        "this needs new records. Leave your Mailgun records in place while you move.",
        "Open each template with notes and fix what they mention, then send yourself a test.",
        "Mailgun automatically adds an unsubscribe footer on some domains, and PostHog doesn't. Add an unsubscribe "
        "link to marketing templates if the domain list mentions this.",
        "Make a template transactional and change your app to send it through PostHog. Pass the values Mailgun took "
        "from t:variables and recipient-variables as variables. Start with a low-risk email.",
        "If you send a lot of email, move it over several days. Mailbox providers slow down mail from a sender "
        "whose volume jumps.",
        "Once nothing sends through Mailgun, remove its DNS records and delete the API key you created for this import.",
    )
    settings = (
        ImportSettingSpec(
            key=REGION_SETTING,
            label="Mailgun region",
            help=(
                "Mailgun keeps data in each region apart. PostHog only sends your key to the region you choose. Your "
                "domains' page in Mailgun shows which region they're in."
            ),
            choices=(
                ImportSettingChoice(value=MailgunRegion.US.value, label="US (api.mailgun.net)"),
                ImportSettingChoice(value=MailgunRegion.EU.value, label="EU (api.eu.mailgun.net)"),
                ImportSettingChoice(value=ALL_REGIONS, label="Both US and EU"),
            ),
        ),
        ImportSettingSpec(
            key=VERSIONS_SETTING,
            label="Template versions",
            help=(
                "Mailgun sends a template's active version unless a send names another. Import the rest if your app "
                "names a version when it sends."
            ),
            choices=(
                ImportSettingChoice(value=ACTIVE_VERSION, label="Active version only"),
                ImportSettingChoice(value=ALL_VERSIONS, label="Every version, each as its own template"),
            ),
            default=ACTIVE_VERSION,
        ),
    )
    steps = (
        ImportStepSpec(
            key="bounces",
            label="Bounces",
            description=(
                "Adds every bounced address, from every domain, to your PostHog suppression list. These block all "
                "email, as they do in Mailgun."
            ),
            count_labels=(
                ("bounced", "Hard bounces, which block all email"),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing_domains", "Domains Mailgun couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="complaints",
            label="Spam complaints",
            description="Adds every address that complained, from every domain, to your PostHog suppression list.",
            count_labels=(
                ("complained", "Spam complaints, which block marketing email only. Mailgun blocks all email to them."),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing_domains", "Domains Mailgun couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="unsubscribes",
            label="Unsubscribes",
            description=(
                "Opts people who unsubscribed from a domain out of all marketing email. People who unsubscribed from "
                "a tag are opted out of a new message category named after it."
            ),
            count_labels=(
                ("opted_out", "People with a new opt-out"),
                ("from_tags", "People who only unsubscribed from certain tags"),
                ("tag_categories", "New categories for tags"),
                ("invalid", "Skipped because the address isn't valid"),
                ("missing_domains", "Domains Mailgun couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="allowlists",
            label="Allowlists",
            description=(
                "Lists what each domain allows. PostHog has no allowlist, so a bounce here can still suppress these "
                "addresses. Nothing is changed in PostHog."
            ),
            count_labels=(
                ("addresses", "Allowed addresses"),
                ("domains", "Allowed domains"),
                ("also_suppressed", "Allowed addresses that are on your PostHog suppression list"),
                ("missing_domains", "Domains Mailgun couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="mailing_lists",
            label="Mailing lists",
            description=(
                "Creates a marketing message category for each list, and opts out the members who left it. PostHog "
                "reads only those members and doesn't create people from your lists."
            ),
            count_labels=(
                ("created", "New categories"),
                ("already_present", "Already in PostHog, left as they are"),
                ("opted_out", "People with a new list opt-out"),
                ("members", "List members, who stay in Mailgun"),
                ("missing_lists", "Lists Mailgun couldn't find, skipped"),
            ),
        ),
        ImportStepSpec(
            key="templates",
            label="Templates",
            description=(
                "Copies account and domain templates into your PostHog library, converted to Liquid, and notes "
                "anything to review. Templates you already have here stay as they are, and none of them send on "
                "their own."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
                ("no_content", "Skipped because they have no content"),
                ("missing", "Mailgun couldn't find these, skipped"),
            ),
        ),
        ImportStepSpec(
            key="domains",
            label="Sending domains",
            description=(
                "Lists your Mailgun domains, their DNS records, and which of them can already send from PostHog. "
                "Domains can't be copied, because PostHog signs mail with its own keys."
            ),
            count_labels=(
                ("ready", "Ready to send from PostHog"),
                ("needs_setup", "Need new DNS records"),
                ("sandbox", "Mailgun sandbox domains, not for PostHog"),
                ("missing_domains", "Domains Mailgun couldn't find, skipped"),
            ),
        ),
    )

    def check_credentials(
        self, team_id: int, api_key: str | None, settings: Mapping[str, str], steps: Sequence[str]
    ) -> ImportCredentials:
        if not api_key:
            raise ImportCredentialsMissing(MISSING_KEY_MESSAGE)
        if not api_key.isascii():
            raise ImportCredentialsInvalid(INVALID_KEY_MESSAGE)
        for region in _regions(settings):
            client = MailgunClient(api_key, region, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
            with _translated_errors(INVALID_KEY_MESSAGE):
                domains = client.get("/v4/domains", {"limit": 1}).get("items") or []
            # Mailgun's Analyst role reads domains and templates, but not suppressions, so ask before the run starts.
            first = domains[0] if domains and isinstance(domains[0], dict) else {}
            if domain := first.get("name"):
                for step in steps:
                    if what := _STEPS_NEEDING_SUPPRESSION_ROLE.get(step):
                        with _translated_errors(CANNOT_READ_MESSAGE.format(what=what)):
                            _probe(client, domain, what, first.get("subaccount_id"))
        return ImportCredentials(api_key=api_key)

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_KEY_MESSAGE)
        clients = {region: MailgunClient(context.api_key, region) for region in _regions(context.settings)}
        with _translated_errors(LOST_ACCESS_MESSAGE):
            match step:
                case "bounces":
                    yield from _fetch_suppression_list(clients, context, checkpoint, "bounces", _save_bounces)
                case "complaints":
                    yield from _fetch_suppression_list(clients, context, checkpoint, "complaints", _save_complaints)
                case "unsubscribes":
                    yield from _fetch_suppression_list(clients, context, checkpoint, "unsubscribes", _save_unsubscribes)
                case "allowlists":
                    yield from _fetch_suppression_list(clients, context, checkpoint, "whitelists", _save_allowlist)
                case "mailing_lists":
                    yield from _fetch_mailing_lists(clients, context, checkpoint)
                case "templates":
                    yield from _fetch_templates(clients, context, checkpoint)
                case "domains":
                    yield from _fetch_domains(clients, context, checkpoint)
                case _:
                    raise UnknownImportStep(f"Mailgun has no import step named {step}.")


def _probe(client: MailgunClient, domain: str, what: str, owner: Any) -> None:
    try:
        client.get(f"/v3/{quoted(domain)}/{what}", {"limit": 1}, str(owner) if owner else None)
    except MailgunNotFound:
        pass


@contextmanager
def _translated_errors(rejected_message: str) -> Iterator[None]:
    try:
        yield
    except MailgunKeyRejected as e:
        raise ImportCredentialsInvalid(rejected_message) from e
    except MailgunRateLimited as e:
        raise ImportProviderUnavailable(RATE_LIMITED_MESSAGE) from e
    except MailgunAPIError as e:
        raise ImportProviderUnavailable(str(e)) from e


def _regions(settings: Mapping[str, str]) -> tuple[MailgunRegion, ...]:
    region = settings.get(REGION_SETTING)
    if region == ALL_REGIONS:
        return (MailgunRegion.US, MailgunRegion.EU)
    return (MailgunRegion(region),) if region else ()


def _position(target: _Target, after: str | None = None) -> StepCheckpoint:
    position: StepCheckpoint = {"region": target.region.value, "owner": target.owner, "name": target.name}
    if after:
        position["after"] = after
    return position


def _remaining_targets(targets: list[_Target], checkpoint: StepCheckpoint | None) -> tuple[list[_Target], str | None]:
    """The targets still to read, and the page to start the first one from. A target deleted since the checkpoint moves
    the step on to the next one."""
    ordered = sorted(targets, key=lambda target: target.position)
    if not checkpoint:
        return ordered, None
    saved = (str(checkpoint.get("region", "")), str(checkpoint.get("owner", "")), str(checkpoint.get("name", "")))
    remaining = [target for target in ordered if target.position >= saved]
    after = checkpoint.get("after") if remaining and remaining[0].position == saved else None
    return remaining, str(after) if after else None


def _read_targets(
    clients: Mapping[MailgunRegion, MailgunClient],
    targets: list[_Target],
    checkpoint: StepCheckpoint | None,
    read_items: Callable[[MailgunClient, _Target, list[dict[str, Any]]], list[dict[str, Any]]] | None,
    save: Callable[[_Target, list[dict[str, Any]], bool], SavedPage],
    on_missing: Callable[[_Target], SavedPage],
) -> Iterator[ImportPage]:
    remaining, first_after = _remaining_targets(targets, checkpoint)
    if not remaining:
        yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    for index, target in enumerate(remaining):
        following = remaining[index + 1] if index + 1 < len(remaining) else None
        after_target = _position(following) if following else None
        client = clients[target.region]
        after = first_after if index == 0 else None
        is_first_page = after is None
        while True:
            try:
                page = client.page(target.path, dict(target.params), after, target.on_behalf_of)
            except MailgunNotFound:
                yield ImportPage(processed=0, save=partial(on_missing, target), checkpoint=after_target)
                break
            items = read_items(client, target, page.items) if read_items else page.items
            yield ImportPage(
                processed=len(page.items),
                save=partial(save, target, items, is_first_page),
                checkpoint=_position(target, page.next_after) if page.next_after else after_target,
            )
            if not page.next_after:
                break
            after = page.next_after
            is_first_page = False


def _domain_targets(
    clients: Mapping[MailgunRegion, MailgunClient], suffix: str, params: Mapping[str, Any] | None = None
) -> list[_Target]:
    return [
        _Target(
            region=region,
            owner=str(domain.get("subaccount_id") or ""),
            name=str(domain["name"]),
            path=f"/v3/{quoted(str(domain['name']))}/{suffix}",
            params=params or {},
            details=domain,
        )
        for region, client in clients.items()
        for domain in client.domains()
        if domain.get("name")
    ]


def _missing_domain(target: _Target) -> SavedPage:
    return SavedPage(
        imported=0,
        counts={"missing_domains": 1},
        warnings=(f"{target.name}: Mailgun couldn't find this domain, so nothing imported from it. Import again.",),
    )


def _normalized_email(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    email = value.replace("\x00", "").strip().lower()
    return email if email_domain(email) and not email.startswith("@") and len(email) <= 512 else None


def _exact_email(value: Any) -> str | None:
    # An opt-out matches the address a send names exactly, so the case stays as Mailgun has it.
    return value.replace("\x00", "").strip() if _normalized_email(value) else None


def _timestamp(value: Any) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _clean(value: Any) -> str:
    return str(value or "").replace("\x00", "")


def _fetch_suppression_list(
    clients: Mapping[MailgunRegion, MailgunClient],
    context: ImportContext,
    checkpoint: StepCheckpoint | None,
    list_name: str,
    save: Callable[[ImportContext, _Target, list[dict[str, Any]], bool], SavedPage],
) -> Iterator[ImportPage]:
    yield from _read_targets(
        clients,
        _domain_targets(clients, list_name, {"limit": SUPPRESSION_PAGE_SIZE}),
        checkpoint,
        None,
        partial(save, context),
        _missing_domain,
    )


def _save_bounces(context: ImportContext, target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for item in items:
        email = _normalized_email(item.get("address"))
        if email is None:
            invalid += 1
            continue
        code, error = _clean(item.get("code")), _clean(item.get("error"))
        imported[email] = ImportedSuppression(
            identifier=email,
            source=SuppressionSource.BOUNCE,
            reason=f"Imported from Mailgun (bounced on {target.name})",
            suppressed_at=_timestamp(item.get("created_at")),
            diagnostic=" ".join(part for part in (code, error) if part) or None,
        )
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
    upgraded = _upgrade_imported_complaints(context.team_id, imported)
    return SavedPage(
        imported=result.total_added + upgraded,
        counts={
            "bounced": result.added.get(SuppressionSource.BOUNCE, 0) + upgraded,
            "already_present": result.already_present - upgraded,
            "invalid": invalid,
        },
    )


def _upgrade_imported_complaints(team_id: int, bounces: Mapping[str, ImportedSuppression]) -> int:
    """A failed bounces step can resume after complaints ran. A complaint this import wrote must then still gain the
    bounce, which is what blocks transactional email. A row someone removed or added by hand stays as it is."""
    rows = list(
        MessageSuppression.objects.for_team(team_id, canonical=True).filter(
            identifier__in=list(bounces),
            source=SuppressionSource.COMPLAINT,
            reason__startswith=COMPLAINT_REASON_PREFIX,
            suppressed=True,
            deleted=False,
            hard_bounced_at__isnull=True,
        )
    )
    now = timezone.now()
    for row in rows:
        bounce = bounces[row.identifier]
        row.source = SuppressionSource.BOUNCE
        row.reason = bounce.reason
        row.hard_bounced_at = bounce.suppressed_at or now
        row.last_bounce_at = bounce.suppressed_at
        row.last_bounce_diagnostic = bounce.diagnostic
    MessageSuppression.objects.for_team(team_id, canonical=True).bulk_update(
        rows, ["source", "reason", "hard_bounced_at", "last_bounce_at", "last_bounce_diagnostic"], batch_size=500
    )
    return len(rows)


def _save_complaints(context: ImportContext, target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for item in items:
        email = _normalized_email(item.get("address"))
        if email is None:
            invalid += 1
            continue
        imported[email] = ImportedSuppression(
            identifier=email,
            source=SuppressionSource.COMPLAINT,
            reason=f"{COMPLAINT_REASON_PREFIX}{target.name})",
            suppressed_at=_timestamp(item.get("created_at")),
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


def _tag_category(tag: str) -> ImportedCategory:
    return ImportedCategory(
        key=_category_key("mailgun_tag_", tag),
        name=tag[:128] or ALL_TAGS,
        description=f"Imported from Mailgun. People unsubscribed from email tagged {tag}.",
    )


def _category_key(prefix: str, value: str) -> str:
    return f"{prefix}{hashlib.sha256(value.encode()).hexdigest()}"[:CATEGORY_KEY_MAX_LENGTH]


def _save_unsubscribes(
    context: ImportContext, _target: _Target, items: list[dict[str, Any]], _first: bool
) -> SavedPage:
    everything: set[str] = set()
    tags_by_email: dict[str, set[str]] = {}
    invalid = 0
    for item in items:
        email = _exact_email(item.get("address"))
        if email is None:
            invalid += 1
            continue
        tags = {_clean(tag) for tag in item.get("tags") or [] if tag}
        # Mailgun's own default for an unsubscribe with no tag is every message from the domain.
        if not tags or ALL_TAGS in tags:
            everything.add(email)
        else:
            tags_by_email.setdefault(email, set()).update(tags)

    categories = {tag: _tag_category(tag) for tags in tags_by_email.values() for tag in tags}
    result = import_categories(context.team_id, categories.values(), context.created_by_id)
    opt_outs: dict[str, list[str]] = {email: [ALL_MESSAGE_PREFERENCE_CATEGORY_ID] for email in everything}
    for email, tags in tags_by_email.items():
        if email not in everything:
            opt_outs[email] = [
                result.ids_by_key[categories[tag].key]
                for tag in sorted(tags)
                if categories[tag].key in result.ids_by_key
            ]
    changed = import_opt_outs(context.team_id, opt_outs, context.created_by_id)
    return SavedPage(
        imported=changed,
        counts={
            "opted_out": changed,
            "from_tags": len(set(tags_by_email) - everything),
            "tag_categories": result.created,
            "invalid": invalid,
        },
    )


def _save_allowlist(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    addresses = [
        email for item in items if item.get("type") != "domain" and (email := _normalized_email(item.get("value")))
    ]
    domains = [_clean(item.get("value")) for item in items if item.get("type") == "domain"]
    also_suppressed = sorted(
        MessageSuppression.objects.for_team(context.team_id, canonical=True)
        .filter(identifier__in=addresses, suppressed=True, deleted=False)
        .values_list("identifier", flat=True)
    )
    notes: list[str] = []
    if also_suppressed:
        notes.append(
            f"On your PostHog suppression list: {', '.join(also_suppressed[:_MAX_NOTED_ITEMS])}. Remove any you still "
            "want to email."
        )
    if domains and first:
        notes.append(f"Allowed domains: {', '.join(domains[:_MAX_NOTED_ITEMS])}.")
    return SavedPage(
        imported=0,
        counts={"addresses": len(addresses), "domains": len(domains), "also_suppressed": len(also_suppressed)},
        items=(
            (
                ImportItem(
                    label=target.name,
                    status="listed",
                    url="/workflows/opt-outs",
                    notes=(
                        "Mailgun never adds these to its bounce list. PostHog has no allowlist, so a bounce here "
                        "suppresses them. Test addresses that are meant to bounce will need removing.",
                        *notes,
                    ),
                ),
            )
            if items and (first or notes)
            else ()
        ),
    )


def _owners(client: MailgunClient) -> list[str]:
    return ["", *client.subaccount_ids()]


def _fetch_mailing_lists(
    clients: Mapping[MailgunRegion, MailgunClient], context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    targets: list[_Target] = []
    for region, client in clients.items():
        for owner in _owners(client):
            after: str | None = None
            while True:
                page = client.page("/v3/lists/pages", {"limit": TEMPLATE_PAGE_SIZE}, after, owner or None)
                targets.extend(
                    _Target(
                        region=region,
                        owner=owner,
                        name=str(mailing_list["address"]),
                        path=f"/v3/lists/{quoted(str(mailing_list['address']))}/members/pages",
                        params={"subscribed": "false", "limit": TEMPLATE_PAGE_SIZE},
                        details=mailing_list,
                    )
                    for mailing_list in page.items
                    if mailing_list.get("address")
                )
                if page.next_after is None:
                    break
                after = page.next_after
    yield from _read_targets(clients, targets, checkpoint, None, partial(_save_list_members, context), _missing_list)


def _missing_list(target: _Target) -> SavedPage:
    return SavedPage(
        imported=0,
        counts={"missing_lists": 1},
        warnings=(f"{target.name}: Mailgun couldn't find this list, so nothing imported from it. Import again.",),
    )


def _list_category(mailing_list: Mapping[str, Any], address: str) -> ImportedCategory:
    description = _clean(mailing_list.get("description"))
    return ImportedCategory(
        key=_category_key("mailgun_list_", address),
        name=(_clean(mailing_list.get("name")) or address)[:128],
        description=f"Imported from the Mailgun list {address}. {description}".strip(),
    )


def _save_list_members(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    category = _list_category(target.details, target.name)
    result = import_categories(context.team_id, [category], context.created_by_id)
    left = {
        email: [result.ids_by_key[category.key]] if category.key in result.ids_by_key else []
        for item in items
        if item.get("subscribed") is not True and (email := _exact_email(item.get("address")))
    }
    changed = import_opt_outs(context.team_id, left, context.created_by_id)
    members = int(target.details.get("members_count") or 0)
    counts: dict[str, int] = {"opted_out": changed}
    items_out: tuple[ImportItem, ...] = ()
    if first:
        counts |= {"created": result.created, "already_present": result.already_present, "members": members}
        items_out = (
            ImportItem(
                label=target.name,
                status="created" if result.created else "skipped",
                url="/workflows/opt-outs",
                notes=(
                    f"Members on this list in Mailgun: {members}. PostHog doesn't create people from a list, and "
                    "their custom variables stay in Mailgun too. To send to this audience, build a cohort from your "
                    "own data or send people's details to PostHog first.",
                    "Sending to the list address, who can post to it, and where replies go don't carry over.",
                ),
            ),
        )
    return SavedPage(imported=changed, counts=counts, items=items_out)


def _template_owner_targets(clients: Mapping[MailgunRegion, MailgunClient]) -> list[_Target]:
    params = {"limit": TEMPLATE_PAGE_SIZE}
    # An empty name sorts first, so account templates run before any domain's.
    account = [
        _Target(region=region, owner=owner, name="", path="/v4/templates", params=params)
        for region, client in clients.items()
        for owner in _owners(client)
    ]
    return [*account, *_domain_targets(clients, "templates", params)]


def _fetch_templates(
    clients: Mapping[MailgunRegion, MailgunClient], context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    all_versions = context.settings.get(VERSIONS_SETTING) == ALL_VERSIONS
    yield from _read_targets(
        clients,
        _template_owner_targets(clients),
        checkpoint,
        partial(_read_template_versions, all_versions=all_versions),
        partial(_save_templates, context),
        _missing_domain,
    )


def _read_template_versions(
    client: MailgunClient, target: _Target, items: list[dict[str, Any]], *, all_versions: bool
) -> list[dict[str, Any]]:
    # The list has no content, so each template costs more requests.
    templates: list[dict[str, Any]] = []
    for item in items:
        name = str(item.get("name") or "")
        path = f"{target.path}/{quoted(name)}"
        try:
            body = client.get(path, {"active": "yes"}, target.on_behalf_of)
            versions = client.versions(path, target.on_behalf_of)
            detail = body.get("template") if isinstance(body.get("template"), dict) else {}
            active = detail.get("version") if isinstance(detail.get("version"), dict) else None
            selected: list[dict[str, Any]] = [active] if active else []
            if all_versions:
                active_tag = active.get("tag") if active else None
                for version in versions:
                    if version.get("tag") and version.get("tag") != active_tag:
                        selected.append(_read_version(client, path, version, target))
            templates.append({**item, **detail, "selected": selected, "version_tags": [v.get("tag") for v in versions]})
        except MailgunNotFound:
            templates.append({**item, "missing": True})
    return templates


def _read_version(client: MailgunClient, path: str, version: dict[str, Any], target: _Target) -> dict[str, Any]:
    body = client.get(f"{path}/versions/{quoted(str(version['tag']))}", None, target.on_behalf_of)
    template = body.get("template") if isinstance(body.get("template"), dict) else {}
    detail = template.get("version") if isinstance(template.get("version"), dict) else None
    return detail or version


def _template_key(target: _Target, name: str, version_tag: str | None) -> str:
    """Stable across imports, so a rerun finds what it made. Mailgun names repeat across domains and regions and can
    hold characters a key can't, so a name that lost characters also carries a hash of the original."""
    scope = [part for part in ("eu" if target.region == MailgunRegion.EU else "", target.owner, target.name) if part]
    return "-".join(
        [
            *(_key_part(part) for part in scope if part),
            _hashed_key_part(name),
            *(["version", _hashed_key_part(version_tag)] if version_tag else []),
        ]
    )[:TEMPLATE_KEY_MAX_LENGTH]


def _key_part(value: str) -> str:
    return _UNSAFE_IN_KEY.sub("-", value).strip("-")


def _hashed_key_part(value: str) -> str:
    safe = _key_part(value)
    if safe == value and len(safe) <= _MAX_KEY_NAME_LENGTH:
        return safe
    digest = hashlib.sha256(value.encode()).hexdigest()[:10]
    return f"{safe[:_MAX_KEY_NAME_LENGTH]}-{digest}".lstrip("-")


def _template_label(target: _Target, name: str, version_tag: str | None) -> str:
    place = target.name or ("EU account" if target.region == MailgunRegion.EU else "")
    suffix = f" (version {version_tag})" if version_tag else ""
    return f"{name} ({place}){suffix}"[:400] if place else f"{name}{suffix}"[:400]


def _save_templates(
    context: ImportContext, target: _Target, templates: list[dict[str, Any]], _first: bool
) -> SavedPage:
    senders = _senders(context.team_id)
    keys = [
        _template_key(target, _clean(template.get("name")), _version_suffix(template, version))
        for template in templates
        for version in template.get("selected", [])
    ]
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = set(MessageTemplate.objects.filter(team_id=context.team_id, key__in=keys).values_list("key", flat=True))
    items: list[ImportItem] = []
    counts: Counter[str] = Counter()
    for template in templates:
        name = _clean(template.get("name"))
        if template.get("missing"):
            counts["missing"] += 1
            items.append(ImportItem(label=name, status="failed", notes=("Mailgun couldn't find this template.",)))
            continue
        selected = template.get("selected", [])
        if not selected:
            counts["no_content"] += 1
            items.append(ImportItem(label=name, status="skipped", notes=("This template has no active version.",)))
            continue
        for version in selected:
            version_tag = _version_suffix(template, version)
            key = _template_key(target, name, version_tag)
            label = _template_label(target, name, version_tag)
            if key in taken:
                counts["already_present"] += 1
                items.append(
                    ImportItem(label=label, status="skipped", notes=(f"A template with the key {key} exists.",))
                )
                continue
            taken.add(key)
            converted = convert_version(version)
            if not converted.has_content:
                counts["no_content"] += 1
                items.append(
                    ImportItem(
                        label=label,
                        status="skipped",
                        notes=("This version has no HTML. If it's written in MJML, export the HTML from Mailgun.",),
                    )
                )
                continue
            email, sender_notes = _email_content(version, converted, senders, target)
            notes = (*converted.notes, *converted.send_notes, *sender_notes, *_other_versions_note(template, version))
            created = create_template(
                context.team_id,
                context.created_by_id,
                {
                    "name": label,
                    "key": key,
                    "description": " ".join(("Imported from Mailgun.", _clean(template.get("description")), *notes)),
                    "type": "email",
                    "content": {"templating": "liquid", "email": email},
                    "tags": [IMPORT_TAG],
                },
            )
            counts["needs_review" if notes else "created"] += 1
            items.append(
                ImportItem(label=label, status="created", url=f"/workflows/library/templates/{created.id}", notes=notes)
            )
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


def _version_suffix(template: dict[str, Any], version: dict[str, Any]) -> str | None:
    # The active version keeps the plain key, because that's what a send without a version gets.
    return None if version.get("active") or len(template.get("selected", [])) == 1 else _clean(version.get("tag"))


def _other_versions_note(template: dict[str, Any], version: dict[str, Any]) -> tuple[str, ...]:
    tags = [_clean(tag) for tag in template.get("version_tags") or [] if tag]
    others = [tag for tag in tags if tag != version.get("tag")]
    if not others or len(template.get("selected", [])) > 1:
        return ()
    shown = ", ".join(others[:_MAX_NOTED_ITEMS])
    more = f" and {len(others) - _MAX_NOTED_ITEMS} more" if len(others) > _MAX_NOTED_ITEMS else ""
    return (f"PostHog imported the active version, {version.get('tag')}. Still in Mailgun: {shown}{more}.",)


def _senders(team_id: int) -> dict[str, IntegrationRecord]:
    return {
        str(sender.config.get("email", "")).lower(): sender
        for sender in IntegrationManager.email.credentials.list(team_id)
    }


def _email_content(
    version: Mapping[str, Any], converted: ConvertedVersion, senders: Mapping[str, IntegrationRecord], target: _Target
) -> tuple[dict[str, Any], tuple[str, ...]]:
    email: dict[str, Any] = {"subject": converted.subject, "html": converted.html}
    headers = version.get("headers") if isinstance(version.get("headers"), dict) else {}
    by_name = {str(key).lower(): value for key, value in headers.items()}
    if reply_to := by_name.get("reply-to"):
        email["replyTo"] = _clean(reply_to)
    display_name, address = parseaddr(_clean(by_name.get("from")))
    if not address:
        fallback = f"postmaster@{target.name}" if target.name else "postmaster at your sending domain"
        return email, (f"This template has no From header, so Mailgun sent it from {fallback}. Choose a sender.",)
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


def _fetch_domains(
    clients: Mapping[MailgunRegion, MailgunClient], context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    empty_regions = []
    targets: list[_Target] = []
    for region, client in clients.items():
        region_targets = _domain_targets({region: client}, "")
        targets.extend(region_targets)
        if not region_targets:
            empty_regions.append(region)
    if empty_regions and not checkpoint:
        warnings = tuple(
            f"Mailgun has no domains in the {region.value.upper()} region for this key. If your domains are in the "
            "other region, import again and choose it."
            for region in empty_regions
        )
        first = sorted(targets, key=lambda target: target.position)[0] if targets else None
        yield ImportPage(
            processed=0,
            save=lambda: SavedPage(imported=0, warnings=warnings),
            checkpoint=_position(first) if first else None,
        )
    remaining, _ = _remaining_targets(targets, checkpoint)
    if not remaining:
        if not empty_regions or checkpoint:
            yield ImportPage(processed=0, save=lambda: SavedPage(imported=0))
        return
    for index, target in enumerate(remaining):
        following = remaining[index + 1] if index + 1 < len(remaining) else None
        client = clients[target.region]
        try:
            detail = client.get(f"/v4/domains/{quoted(target.name)}", None, target.on_behalf_of)
        except MailgunNotFound:
            yield ImportPage(
                processed=1,
                save=partial(_missing_domain, target),
                checkpoint=_position(following) if following else None,
            )
            continue
        tracking = _read_tracking(client, target)
        yield ImportPage(
            processed=1,
            save=partial(_save_domain, context, target, detail, tracking),
            checkpoint=_position(following) if following else None,
        )


def _read_tracking(client: MailgunClient, target: _Target) -> dict[str, Any]:
    try:
        body = client.get(f"/v3/domains/{quoted(target.name)}/tracking", None, target.on_behalf_of)
    except MailgunNotFound:
        return {}
    tracking = body.get("tracking")
    return tracking if isinstance(tracking, dict) else {}


def _save_domain(
    context: ImportContext, target: _Target, detail: dict[str, Any], tracking: dict[str, Any]
) -> SavedPage:
    domain = detail.get("domain") if isinstance(detail.get("domain"), dict) else target.details
    senders = [
        sender
        for sender in IntegrationManager.email.credentials.list(context.team_id)
        if str(sender.config.get("domain", "")).lower() == target.name.lower()
    ]
    ready = any(sender.config.get("verified") for sender in senders)
    is_sandbox = domain.get("type") == "sandbox"
    notes: list[str] = [f"Mailgun region: {target.region.value.upper()}."]
    if is_sandbox:
        notes.append("This is a Mailgun sandbox domain. It can't send from PostHog.")
    elif not ready:
        notes.append(
            "Waiting for DNS. Check the records on this domain's page."
            if senders
            else "Add this domain in PostHog to get its DNS records."
        )
    if domain.get("is_disabled") or isinstance(domain.get("disabled"), dict):
        notes.append("Mailgun has disabled this domain.")
    if domain.get("state") and domain.get("state") != "active":
        notes.append(f"Mailgun lists this domain as {_clean(domain.get('state'))}.")
    if target.owner:
        notes.append(f"It belongs to the Mailgun subaccount {target.owner}.")
    records = [*(detail.get("sending_dns_records") or []), *(detail.get("receiving_dns_records") or [])]
    if _uses_mail_from_label(records, MAIL_FROM_DEFAULT):
        notes.append(
            f"Mailgun already uses the {MAIL_FROM_DEFAULT} subdomain here. Choose a different MAIL FROM subdomain in "
            "PostHog, or both tools will share one MX record and one of them will break."
        )
    if described := _describe_records(records):
        notes.append(f"Mailgun DNS records to remove after you move: {described}.")
    if _adds_unsubscribe_footer(tracking):
        notes.append(
            "Mailgun adds an unsubscribe footer to mail from this domain. PostHog doesn't, so add an unsubscribe link "
            "to its marketing templates."
        )
    counts = {"sandbox" if is_sandbox else "ready" if ready else "needs_setup": 1}
    return SavedPage(
        imported=0,
        counts=counts,
        items=(
            ImportItem(
                label=target.name,
                status="listed",
                url=f"/workflows/channels/email/{senders[0].id}" if senders else "/workflows/channels",
                notes=tuple(notes),
            ),
        ),
    )


def _uses_mail_from_label(records: list[Any], label: str) -> bool:
    return any(
        isinstance(record, dict)
        and str(record.get("record_type", "")).upper() == "MX"
        and str(record.get("name", "")).split(".")[0].lower() == label
        for record in records
    )


def _describe_records(records: list[Any]) -> str:
    return "; ".join(
        f"{_clean(record.get('record_type'))} {_clean(record.get('name') or '(domain)')}"
        for record in records
        if isinstance(record, dict)
    )


def _adds_unsubscribe_footer(tracking: dict[str, Any]) -> bool:
    unsubscribe = tracking.get("unsubscribe")
    if not isinstance(unsubscribe, dict) or not unsubscribe.get("active"):
        return False
    return any(unsubscribe.get(footer) not in (None, "", "off") for footer in ("html_footer", "text_footer"))
