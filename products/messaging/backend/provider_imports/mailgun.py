"""Imports suppressions and mailing list opt-outs from Mailgun.

Mailgun keeps suppressions and mailing lists per region and mostly per domain, while PostHog keeps them per team. So
every step walks a sorted list of targets (a domain or a list) and its checkpoint names the target and the page inside
it. Merging domains can only block more email than Mailgun does, never less.

Mailgun's API has no automations, so nothing here makes a workflow. People never move: list steps read only who left.
"""

import hashlib
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import field
from datetime import datetime
from email.utils import parsedate_to_datetime
from functools import partial
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping.manager import resolve_effective_team_id

from products.messaging.backend.models.message_preferences import ALL_MESSAGE_PREFERENCE_CATEGORY_ID
from products.messaging.backend.models.message_suppression import MessageSuppression, SuppressionSource
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
from products.messaging.backend.provider_imports.emails import exact_email, normalized_email
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
NO_DOMAINS_MESSAGE = (
    "Mailgun has no domains for this key in the {regions} region. Everything PostHog imports belongs to a domain, so "
    "nothing would come across. Check which region your domains are in on Mailgun's domains page and choose it."
)
COMPLAINT_REASON_PREFIX = "Imported from Mailgun (spam complaint on "
REGION_SETTING = "region"
ALL_REGIONS = "both"
ALL_TAGS = "*"
CATEGORY_KEY_MAX_LENGTH = 64
_MAX_NOTED_ITEMS = 5
_STEPS_NEEDING_SUPPRESSION_ROLE = {step: step for step in ("bounces", "complaints", "unsubscribes")}


def _position_key(region: str, owner: str, name: str) -> str:
    # The separator sorts below every character in a name, so the key sorts field by field.
    return "\x00".join((region, owner, name))


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
    def position(self) -> str:
        return _position_key(self.region.value, self.owner, self.name)

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
        "webhooks, tracking settings, send history and stats stay in Mailgun, so rebuild what you need."
    )
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so "
        "this needs new records. Leave your Mailgun records in place while you move.",
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
                ("already_opted_out", "People already opted out in PostHog, left as they are"),
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
                ("already_opted_out", "People already opted out in PostHog, left as they are"),
                ("members", "List members, who stay in Mailgun"),
                ("missing_lists", "Lists Mailgun couldn't find, skipped"),
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
        regions = _regions(settings)
        regions_with_domains = 0
        for region in regions:
            client = MailgunClient(api_key, region, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
            with _translated_errors(INVALID_KEY_MESSAGE):
                domains = client.get("/v4/domains", {"limit": 1, "include_subaccounts": "true"}).get("items") or []
            regions_with_domains += bool(domains)
            # Mailgun's Analyst role reads domains and templates, but not suppressions, so ask before the run starts.
            first = domains[0] if domains and isinstance(domains[0], dict) else {}
            if domain := first.get("name"):
                for step in steps:
                    if what := _STEPS_NEEDING_SUPPRESSION_ROLE.get(step):
                        with _translated_errors(CANNOT_READ_MESSAGE.format(what=what)):
                            _probe(client, domain, what, first.get("subaccount_id"))
        if regions and not regions_with_domains:
            raise ImportCredentialsInvalid(
                NO_DOMAINS_MESSAGE.format(regions=" or ".join(region.value.upper() for region in regions))
            )
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
    saved = _position_key(
        str(checkpoint.get("region", "")), str(checkpoint.get("owner", "")), str(checkpoint.get("name", ""))
    )
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
    place = target.name or "Account templates"
    return SavedPage(
        imported=0,
        counts={"missing_domains": 1},
        warnings=(f"{place}: Mailgun couldn't find this, so nothing imported from it. Import again.",),
    )


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
        email = normalized_email(item.get("address"))
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
    # First, so a complaint this import wrote turns into a bounce instead of staying a complaint.
    upgraded = _upgrade_imported_complaints(context.team_id, imported)
    result = import_suppressions(context.team_id, imported.values(), context.created_by_id)
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
    # Imported rows live on the parent project of a child environment.
    suppressions = MessageSuppression.objects.for_team(resolve_effective_team_id(team_id), canonical=True)
    rows = list(
        suppressions.filter(
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
    suppressions.bulk_update(
        rows, ["source", "reason", "hard_bounced_at", "last_bounce_at", "last_bounce_diagnostic"], batch_size=500
    )
    return len(rows)


def _save_complaints(context: ImportContext, target: _Target, items: list[dict[str, Any]], _first: bool) -> SavedPage:
    imported: dict[str, ImportedSuppression] = {}
    invalid = 0
    for item in items:
        email = normalized_email(item.get("address"))
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
        public_description="",
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
        email = exact_email(item.get("address"))
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
            "already_opted_out": sum(1 for categories in opt_outs.values() if categories) - changed,
            "from_tags": len(set(tags_by_email) - everything),
            "tag_categories": result.created,
            "invalid": invalid,
        },
    )


def _save_allowlist(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    addresses = [
        email for item in items if item.get("type") != "domain" and (email := normalized_email(item.get("value")))
    ]
    domains = [_clean(item.get("value")) for item in items if item.get("type") == "domain"]
    # Matching against the suppression list would let a workflow-only key learn who is suppressed, so this only points
    # at the list.
    notes: list[str] = []
    if addresses:
        notes.append("Check your PostHog suppression list for any of these addresses you still want to email.")
    if domains and first:
        notes.append(f"Allowed domains: {', '.join(domains[:_MAX_NOTED_ITEMS])}.")
    return SavedPage(
        imported=0,
        counts={"addresses": len(addresses), "domains": len(domains)},
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
            if items and first
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
        # A list's description is the sender's own note, so recipients don't see it.
        public_description="",
    )


def _save_list_members(context: ImportContext, target: _Target, items: list[dict[str, Any]], first: bool) -> SavedPage:
    category = _list_category(target.details, target.name)
    result = import_categories(context.team_id, [category], context.created_by_id)
    left = {
        email: [result.ids_by_key[category.key]] if category.key in result.ids_by_key else []
        for item in items
        if item.get("subscribed") is not True and (email := exact_email(item.get("address")))
    }
    changed = import_opt_outs(context.team_id, left, context.created_by_id)
    members = int(target.details.get("members_count") or 0)
    counts: dict[str, int] = {
        "opted_out": changed,
        "already_opted_out": sum(1 for categories in left.values() if categories) - changed,
    }
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
