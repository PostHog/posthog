"""Imports suppressions and templates from Postmark, and lists what stays behind.

Postmark has no read-only token. A server token reads one server. An account token also reads domains and senders, and
lists each server's tokens, which the import uses and never stores. The run keeps the token it was given only until it
ends, and a new import asks for it again.

Suppressions belong to a message stream in Postmark and to the whole project in PostHog, so each address takes its
strongest reason across every stream. A suppression dump has no pages, so a step reads all of them, sorts by address,
and saves a batch at a time. The last saved address is where a retried step continues.
"""

import re
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from functools import partial
from typing import Any
from urllib.parse import urlparse

from django.utils.dateparse import parse_datetime

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationRecord

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
from products.messaging.backend.provider_imports.emails import normalized_email
from products.messaging.backend.provider_imports.postmark_templates import convert_template
from products.messaging.backend.services.imported_data import (
    ImportedCategory,
    ImportedSuppression,
    code_email_keys,
    import_categories,
    import_opt_outs,
    import_suppressions,
)
from products.messaging.backend.services.message_templates import create_template
from products.messaging.backend.services.postmark_client import (
    DUMP_TIMEOUT_SECONDS,
    TEMPLATE_NOT_FOUND_CODE,
    PostmarkAPIError,
    PostmarkClient,
    PostmarkRateLimited,
    PostmarkServer,
    PostmarkTokenCannotRead,
    PostmarkTokenRejected,
    TokenKind,
    identify_token,
)

# The token check runs on the request path, so it gets a short timeout and doesn't wait out a rate limit.
CREDENTIAL_CHECK_TIMEOUT_SECONDS = 10
MISSING_TOKEN_MESSAGE = "Enter your Postmark token. PostHog doesn't keep it between imports."
EXPIRED_TOKEN_MESSAGE = "PostHog deleted the Postmark token when this import ended. Start a new import."
INVALID_TOKEN_MESSAGE = (
    "Postmark rejected this token. Copy a server token from your server's API Tokens tab, or the account token from "
    "your account's API Tokens page, and check that it's still active."
)
TOO_LITTLE_ACCESS_MESSAGE = (
    "This token can't read all of your Postmark data. Ask your account owner or an account admin for a token with "
    "access to this server, or for the account token."
)
RATE_LIMITED_MESSAGE = "Postmark kept asking PostHog to slow down. Import again later."
# Postmark's own value for testing sends. It reads no real data.
TEST_TOKEN = "POSTMARK_API_TEST"
IMPORT_TAG = "imported-from-postmark"
SUPPRESSION_BATCH_SIZE = 500
TEMPLATE_KEY_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,400}")
CATEGORY_KEY_PREFIX = "postmark_"
# The stream every server has for broadcasts. Mail on it is plain marketing email in PostHog, with no category.
DEFAULT_BROADCAST_STREAM = "broadcast"
SENDING_STREAM_TYPES = {"Transactional", "Broadcasts"}
# The label PostHog uses for a sender's MAIL FROM subdomain unless the person picks another.
MAIL_FROM_DEFAULT = "feedback"
_REASON_RANK = {"HardBounce": 3, "SpamComplaint": 2, "ManualSuppression": 1}
_REASON_TEXT = {
    "Customer": "Imported from Postmark (added by your team)",
    "Admin": "Imported from Postmark (added by Postmark)",
}


class PostmarkImportProvider(ImportProvider):
    key = ImportProviderKey.POSTMARK.value
    label = ImportProviderKey.POSTMARK.label
    retains_credentials = False
    resumes_after_failure = True
    feature_flag = "workflows-postmark-import"
    api_key_label = "Postmark server or account token"
    api_key_help = (
        "Postmark has no read-only tokens. PostHog only reads from your account, deletes the token as soon as the "
        "import ends, and asks for it again next time. A server token imports one server. The account token imports "
        "every live server and also lists your domains and senders."
    )
    api_key_url = "https://account.postmarkapp.com/api_tokens"
    not_imported = (
        "Postmark has no automations or contact lists to import. Domains, senders, webhooks, inbound streams, SMTP "
        "settings, send history, stats and tokens stay in Postmark, so rebuild what you need."
    )
    next_steps = (
        "Add each sending domain in PostHog and publish its DNS records. PostHog signs mail with its own keys, so "
        "this needs new records. Leave your Postmark records in place, because both tools can sign mail for one domain "
        "while you move.",
        "Open each template with notes and fix what they mention, choose a sender, then send yourself a test.",
        "Make a template transactional and change your app to send it through PostHog. Start with a low-risk email "
        "and move the rest one at a time.",
        "If you send a lot of email, move it over several days. Mailbox providers slow down mail from a sender "
        "whose volume jumps.",
        "Point your webhooks at their PostHog replacements, or rebuild them as workflows.",
        "Once nothing sends through Postmark, remove its DNS records and revoke the token you used for this import.",
    )
    steps = (
        ImportStepSpec(
            key="streams",
            label="Servers and message streams",
            description=(
                "Lists each server and its streams. Creates a marketing message category for each broadcast stream you "
                "added yourself."
            ),
            count_labels=(
                ("servers", "Servers read"),
                ("streams", "Message streams read"),
                ("categories_created", "New categories"),
                ("categories_present", "Categories already in PostHog, left as they are"),
                ("servers_skipped", "Servers skipped"),
            ),
        ),
        ImportStepSpec(
            key="suppressions",
            label="Suppressions",
            description=(
                "Reads the suppressions of each transactional and broadcast stream. Each address gets the strongest "
                "reason it has on any stream."
            ),
            count_labels=(
                ("bounced", "Hard bounces, which block all email"),
                ("complained", "Spam complaints, which block marketing email only"),
                ("manual", "Added by your team or Postmark, which block marketing email only"),
                ("unsubscribed", "Unsubscribed, now opted out of all marketing email"),
                ("already_present", "Already in PostHog, left as they are"),
                ("invalid", "Skipped because the address or reason isn't valid"),
                (
                    "transactional_block_lost",
                    "Blocked on a transactional stream in Postmark for a reason other than a hard bounce. PostHog "
                    "still sends them transactional email.",
                ),
            ),
        ),
        ImportStepSpec(
            key="templates",
            label="Templates",
            description=(
                "Copies each template into your PostHog library with its alias as the key, with its layout copied into "
                "it and notes on anything to review. Postmark templates don't name a sender, so choose one on each. "
                "Templates you already have here stay as they are."
            ),
            count_labels=(
                ("created", "New templates"),
                ("needs_review", "New templates to review"),
                ("already_present", "Already in PostHog, left as they are"),
                ("layouts", "Layouts read"),
                ("unreadable", "Templates Postmark no longer has"),
            ),
        ),
        ImportStepSpec(
            key="domains",
            label="Sending domains and senders",
            description=(
                "Lists your Postmark domains and sender signatures and which can already send from PostHog. PostHog "
                "signs mail with its own keys, so each one needs new DNS records. This needs the account token."
            ),
            count_labels=(
                ("ready", "Ready to send from PostHog"),
                ("needs_setup", "Need new DNS records"),
                ("senders", "Sender signatures"),
                ("needs_account_token", "Not read, because this needs the account token"),
            ),
        ),
        ImportStepSpec(
            key="webhooks",
            label="Webhooks",
            description="Lists each webhook so you can rebuild it. Webhooks stay in Postmark.",
            count_labels=(("listed", "Webhooks to rebuild"),),
        ),
    )

    def check_credentials(self, team_id: int, api_key: str | None) -> ImportCredentials:
        if not api_key:
            raise ImportCredentialsMissing(MISSING_TOKEN_MESSAGE)
        if not api_key.isascii() or api_key == TEST_TOKEN:
            raise ImportCredentialsInvalid(INVALID_TOKEN_MESSAGE)
        with _translated_errors():
            identify_token(api_key, timeout=CREDENTIAL_CHECK_TIMEOUT_SECONDS, max_rate_limit_waits=0)
        return ImportCredentials(api_key=api_key)

    def run_step(self, step: str, context: ImportContext, checkpoint: StepCheckpoint | None) -> Iterator[ImportPage]:
        if not context.api_key:
            raise ImportCredentialsMissing(EXPIRED_TOKEN_MESSAGE)
        with _translated_errors():
            client = identify_token(context.api_key)
            match step:
                case "streams":
                    yield from _fetch_streams(client, context, checkpoint)
                case "suppressions":
                    yield from _fetch_suppressions(client, context, checkpoint)
                case "templates":
                    yield from _fetch_templates(client, context, checkpoint)
                case "domains":
                    yield from _fetch_domains(client, context, checkpoint)
                case "webhooks":
                    yield from _fetch_webhooks(client, context, checkpoint)
                case _:
                    raise UnknownImportStep(f"Postmark has no import step named {step}.")


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except PostmarkTokenCannotRead as e:
        raise ImportCredentialsInvalid(TOO_LITTLE_ACCESS_MESSAGE) from e
    except PostmarkTokenRejected as e:
        raise ImportCredentialsInvalid(INVALID_TOKEN_MESSAGE) from e
    except PostmarkRateLimited as e:
        raise ImportProviderUnavailable(RATE_LIMITED_MESSAGE) from e
    except PostmarkAPIError as e:
        raise ImportProviderUnavailable(str(e)) from e


@frozen
class _ServerSelection:
    importable: list[PostmarkServer]
    skipped: list[PostmarkServer]


def _importable_servers(client: PostmarkClient) -> _ServerSelection:
    """The servers an import reads, and the ones it skips. A sandbox server never delivers, so its suppressions aren't
    real. Handing over that server's own token still imports it, because then someone picked it."""
    servers = client.servers()
    if client.kind == TokenKind.SERVER:
        return _ServerSelection(importable=servers, skipped=[])
    importable = [server for server in servers if server.delivery_type != "Sandbox" and server.token]
    return _ServerSelection(importable=importable, skipped=[server for server in servers if server not in importable])


def _sending_streams(client: PostmarkClient) -> list[dict[str, Any]]:
    streams = client.get("/message-streams").get("MessageStreams")
    if not isinstance(streams, list):
        raise PostmarkAPIError("Postmark sent an unexpected response for /message-streams.")
    # Postmark leaves archived streams out of this list by default, and an archived stream sends nothing.
    return [stream for stream in streams if stream.get("MessageStreamType") in SENDING_STREAM_TYPES]


def _category_key(server_id: int, stream_id: str) -> str:
    return f"{CATEGORY_KEY_PREFIX}{server_id}_{stream_id}"[:64]


def _fetch_streams(
    client: PostmarkClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    selection = _importable_servers(client)
    importable, skipped = selection.importable, selection.skipped
    after = _after_server(checkpoint)
    remaining = [server for server in importable if server.id > after]
    if checkpoint is None and skipped:
        yield ImportPage(
            processed=len(skipped),
            save=partial(_save_skipped_servers, skipped),
            checkpoint={"after_server": 0} if remaining else None,
        )
    for index, server in enumerate(remaining):
        streams = client.for_server(server).get(
            "/message-streams", {"MessageStreamType": "All", "IncludeArchivedStreams": "true"}
        )
        rows = streams.get("MessageStreams")
        if not isinstance(rows, list):
            raise PostmarkAPIError("Postmark sent an unexpected response for /message-streams.")
        yield ImportPage(
            processed=len(rows),
            save=partial(_save_streams, context, server, rows, len(importable)),
            checkpoint={"after_server": server.id} if index < len(remaining) - 1 else None,
        )


def _after_server(checkpoint: StepCheckpoint | None) -> int:
    return int(checkpoint.get("after_server", 0)) if checkpoint else 0


def _save_skipped_servers(skipped: list[PostmarkServer]) -> SavedPage:
    items = tuple(
        ImportItem(
            label=f"{server.name} (server)",
            status="skipped",
            notes=(
                "This is a sandbox server, so it never delivers mail and its suppressions aren't real. To import its "
                "templates, run an import with this server's token."
                if server.delivery_type == "Sandbox"
                else "Postmark shares no token for this server. Run an import with this server's token.",
            ),
        )
        for server in skipped
    )
    return SavedPage(imported=0, counts={"servers_skipped": len(skipped)}, items=items)


def _save_streams(
    context: ImportContext, server: PostmarkServer, streams: list[dict[str, Any]], server_count: int
) -> SavedPage:
    live = [stream for stream in streams if not stream.get("ArchivedAt")]
    custom_broadcasts = [
        stream
        for stream in live
        if stream.get("MessageStreamType") == "Broadcasts" and stream.get("ID") != DEFAULT_BROADCAST_STREAM
    ]
    result = import_categories(
        context.team_id,
        [
            ImportedCategory(
                key=_category_key(server.id, str(stream.get("ID"))),
                name=str(stream.get("Name") or stream.get("ID"))[:128],
                description=str(stream.get("Description") or ""),
                # A stream's description is the sender's own note, so recipients don't see it.
                public_description="",
            )
            for stream in custom_broadcasts
        ],
        context.created_by_id,
    )
    prefix = f"{server.name}: " if server_count > 1 else ""
    items = [ImportItem(label=f"{server.name} (server)", status="listed", notes=_server_notes(server))]
    items += [
        ImportItem(
            label=f"{prefix}{stream.get('Name') or stream.get('ID')} ({stream.get('ID')})",
            status="listed",
            notes=_stream_notes(stream),
        )
        for stream in streams
    ]
    return SavedPage(
        imported=result.created,
        counts={
            "servers": 1,
            "streams": len(streams),
            "categories_created": result.created,
            "categories_present": result.already_present,
        },
        items=tuple(items),
    )


def _server_notes(server: PostmarkServer) -> tuple[str, ...]:
    notes: list[str] = []
    if server.settings.get("SmtpApiActivated"):
        notes.append("PostHog has no SMTP service, so an app that sends over SMTP needs to change to the send API.")
    if server.settings.get("TrackOpens") or server.settings.get("TrackLinks") not in (None, "None"):
        notes.append("Postmark tracks opens or clicks on this server. Check the tracking setting on each email.")
    if server.delivery_type == "Sandbox":
        notes.append("This is a sandbox server, so it never delivers mail. Its suppressions aren't real addresses.")
    return tuple(notes)


def _stream_notes(stream: dict[str, Any]) -> tuple[str, ...]:
    stream_type = stream.get("MessageStreamType")
    if stream.get("ArchivedAt"):
        return ("This stream is archived in Postmark, so PostHog doesn't read it.",)
    if stream_type == "Inbound":
        return ("Inbound email stays in Postmark, because PostHog can't receive email.",)
    if stream_type == "Transactional":
        return (
            "Mail on this stream becomes a transactional template in PostHog, which only a hard bounce blocks. "
            "Postmark also blocks spam complaints and manual entries on this stream.",
        )
    if stream.get("ID") == DEFAULT_BROADCAST_STREAM:
        return ("Mail on this stream becomes marketing email in PostHog.",)
    return ("Choose this stream's new category on the marketing email that used it.",)


@frozen
class _Suppression:
    address: str
    # Each spelling Postmark has for the address. An opt-out matches the address a send names exactly, unlike a
    # suppression row.
    original_addresses: frozenset[str]
    reason: str
    origin: str
    created_at: str
    on_transactional_stream: bool


def _dump_rows(client: PostmarkClient, stream_id: str) -> list[dict[str, Any]]:
    body = client.get(f"/message-streams/{stream_id}/suppressions/dump", timeout=DUMP_TIMEOUT_SECONDS)
    rows = body.get("Suppressions")
    if not isinstance(rows, list):
        raise PostmarkAPIError("Postmark sent an unexpected response for a suppression list.")
    return rows


def _fetch_suppressions(
    client: PostmarkClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    importable = _importable_servers(client).importable
    merged: dict[str, _Suppression] = {}
    invalid = 0
    for server in importable:
        server_client = client.for_server(server)
        for stream in _sending_streams(server_client):
            rows = _dump_rows(server_client, str(stream.get("ID")))
            invalid += _merge(merged, rows, stream.get("MessageStreamType") == "Transactional")

    after = str(checkpoint.get("after_address", "")) if checkpoint else ""
    addresses = [address for address in sorted(merged) if address > after]
    if checkpoint is None and invalid:
        yield ImportPage(
            processed=invalid,
            save=lambda: SavedPage(imported=0, counts={"invalid": invalid}),
            checkpoint={"after_address": ""} if addresses else None,
        )
    for start in range(0, len(addresses), SUPPRESSION_BATCH_SIZE):
        batch = [merged[address] for address in addresses[start : start + SUPPRESSION_BATCH_SIZE]]
        has_more = start + SUPPRESSION_BATCH_SIZE < len(addresses)
        yield ImportPage(
            processed=len(batch),
            save=partial(_save_suppressions, context, batch),
            checkpoint={"after_address": batch[-1].address} if has_more else None,
        )


def _merge(merged: dict[str, _Suppression], rows: list[dict[str, Any]], is_transactional: bool) -> int:
    invalid = 0
    for row in rows:
        address = normalized_email(row.get("EmailAddress"))
        reason = str(row.get("SuppressionReason"))
        origin = str(row.get("Origin"))
        if address is None or reason not in _REASON_RANK:
            invalid += 1
            continue
        current = merged.get(address)
        on_transactional_stream = is_transactional or (current is not None and current.on_transactional_stream)
        spellings = frozenset({str(row["EmailAddress"]).strip()}) | (
            current.original_addresses if current else frozenset()
        )
        if current is None or _rank(reason, origin) > _rank(current.reason, current.origin):
            merged[address] = _Suppression(
                address=address,
                original_addresses=spellings,
                reason=reason,
                origin=origin,
                created_at=str(row.get("CreatedAt") or ""),
                on_transactional_stream=on_transactional_stream,
            )
        else:
            merged[address] = replace(
                current, original_addresses=spellings, on_transactional_stream=on_transactional_stream
            )
    return invalid


def _rank(reason: str, origin: str) -> int:
    # A block someone added outranks the recipient's own unsubscribe, whichever stream lists it first.
    return _REASON_RANK[reason] * 2 + (0 if origin == "Recipient" else 1)


def _save_suppressions(context: ImportContext, batch: list[_Suppression]) -> SavedPage:
    # Unsubscribing is a choice a person can change later, so it lands with the other choices, not on the block list.
    # A send with no category only checks the opt-out from everything, so a narrower opt-out could miss one.
    unsubscribed = [row for row in batch if row.reason == "ManualSuppression" and row.origin == "Recipient"]
    listed = [row for row in batch if row.reason != "ManualSuppression" or row.origin != "Recipient"]
    result = import_suppressions(context.team_id, [_to_imported(row) for row in listed], context.created_by_id)
    opt_outs = {
        address: [ALL_MESSAGE_PREFERENCE_CATEGORY_ID]
        for row in unsubscribed
        for address in (row.address, *row.original_addresses)
    }
    opted_out = min(import_opt_outs(context.team_id, opt_outs, context.created_by_id), len(unsubscribed))
    return SavedPage(
        imported=result.total_added + opted_out,
        counts={
            "bounced": result.added.get(SuppressionSource.BOUNCE, 0),
            "complained": result.added.get(SuppressionSource.COMPLAINT, 0),
            "manual": result.added.get(SuppressionSource.MANUAL, 0),
            "unsubscribed": opted_out,
            "already_present": result.already_present + len(unsubscribed) - opted_out,
            "transactional_block_lost": sum(
                1 for row in batch if row.on_transactional_stream and row.reason != "HardBounce"
            ),
        },
    )


def _to_imported(row: _Suppression) -> ImportedSuppression:
    match row.reason:
        case "HardBounce":
            source, reason = SuppressionSource.BOUNCE, "Imported from Postmark (hard bounce)"
        case "SpamComplaint":
            source, reason = SuppressionSource.COMPLAINT, "Imported from Postmark (spam complaint)"
        case _:
            source = SuppressionSource.MANUAL
            reason = _REASON_TEXT.get(row.origin, "Imported from Postmark (added by your team)")
    return ImportedSuppression(
        identifier=row.address, source=source, reason=reason, suppressed_at=_timestamp(row.created_at)
    )


def _timestamp(value: str) -> datetime | None:
    try:
        return parse_datetime(value)
    except ValueError:
        return None


def _fetch_templates(
    client: PostmarkClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    importable = _importable_servers(client).importable
    start_server = int(checkpoint.get("server", 0)) if checkpoint else 0
    start_offset = int(checkpoint.get("offset", 0)) if checkpoint else 0
    remaining = [server for server in importable if server.id >= start_server]
    for index, server in enumerate(remaining):
        server_client = client.for_server(server)
        layouts: dict[str, dict[str, Any] | None] = {}
        offset = start_offset if server.id == start_server else 0
        for page, next_offset in server_client.offset_pages("/templates", "Templates", {}, offset=offset):
            next_server = remaining[index + 1] if index + 1 < len(remaining) else None
            yield _template_page(server_client, context, server, page, layouts, next_offset, next_server)


def _template_page(
    client: PostmarkClient,
    context: ImportContext,
    server: PostmarkServer,
    page: list[dict[str, Any]],
    layouts: dict[str, dict[str, Any] | None],
    next_offset: int | None,
    next_server: PostmarkServer | None,
) -> ImportPage:
    templates: list[dict[str, Any]] = []
    shadowed: set[int] = set()
    missing = 0
    layout_rows = [row for row in page if row.get("TemplateType") == "Layout"]
    for row in page:
        if row.get("TemplateType") == "Layout":
            continue
        # The list has no content, so each template costs one more request.
        template = _read_template(client, row.get("Alias") or row.get("TemplateId"))
        if template is None:
            missing += 1
            continue
        alias = template.get("LayoutTemplate")
        if alias and alias not in layouts:
            layouts[alias] = _read_template(client, alias)
        if _alias_shadowed(client, template):
            shadowed.add(template["TemplateId"])
        templates.append(template)
    if next_offset is not None:
        checkpoint: StepCheckpoint | None = {"server": server.id, "offset": next_offset}
    elif next_server is not None:
        checkpoint = {"server": next_server.id, "offset": 0}
    else:
        checkpoint = None
    return ImportPage(
        processed=len(page),
        save=partial(
            _save_templates, context, server, templates, frozenset(shadowed), dict(layouts), layout_rows, missing
        ),
        checkpoint=checkpoint,
    )


def _read_template(client: PostmarkClient, reference: Any) -> dict[str, Any] | None:
    try:
        return client.get(f"/templates/{reference}")
    except PostmarkAPIError as e:
        # A template can go away between the list and the read, and a layout can be missing. The rest carries on.
        if e.status_code == 404 or e.error_code == TEMPLATE_NOT_FOUND_CODE:
            return None
        raise


def _alias_key(alias: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "-", alias)[:400]


def _alias_shadowed(client: PostmarkClient, template: dict[str, Any]) -> bool:
    """Whether another template on the server has, as its exact alias, the key this template's alias turns into."""
    alias = str(template.get("Alias") or "").strip()
    if not alias or TEMPLATE_KEY_PATTERN.fullmatch(alias):
        return False
    other = _read_template(client, _alias_key(alias))
    return other is not None and other.get("TemplateId") != template.get("TemplateId")


def _template_key(template: dict[str, Any], shadowed: frozenset[int]) -> tuple[str, tuple[str, ...]]:
    """The key and any note about it. Postmark allows a `.` in an alias, and PostHog's keys don't."""
    alias = str(template.get("Alias") or "").strip()
    if not alias:
        return f"postmark-{template.get('TemplateId')}"[:400], ()
    if TEMPLATE_KEY_PATTERN.fullmatch(alias):
        return alias, ()
    key = _alias_key(alias)
    if template.get("TemplateId") in shadowed:
        # The template whose alias is the key keeps it, whichever of the two an import reads first.
        suffix = f"-{template['TemplateId']}"
        key = f"{key[: 400 - len(suffix)]}{suffix}"
    return key, (f"PostHog keys can't contain every character in the alias {alias}, so the key is {key}.",)


def _server_tag(server: PostmarkServer) -> str:
    return f"postmark-server-{server.id}"


def _save_templates(
    context: ImportContext,
    server: PostmarkServer,
    templates: list[dict[str, Any]],
    shadowed: frozenset[int],
    layouts: dict[str, dict[str, Any] | None],
    layout_rows: list[dict[str, Any]],
    missing: int,
) -> SavedPage:
    keys = [_template_key(template, shadowed)[0] for template in templates]
    keys += [f"{key}-{server.id}" for key in keys]
    # A deleted template counts too: importing again must not bring back one someone deleted.
    taken = {
        str(row.key): {item.tag.name for item in row.tagged_items.all()}
        for row in MessageTemplate.objects.filter(team_id=context.team_id, key__in=keys)
        .only("id", "key")
        .prefetch_related("tagged_items__tag")
    }
    # A code email's key counts as someone else's, so the template is skipped and the code email keeps sending.
    for key in code_email_keys(context.team_id, keys):
        taken.setdefault(key, set())

    items: list[ImportItem] = []
    counts: Counter[str] = Counter({"layouts": len(layout_rows), "unreadable": missing})
    for template in templates:
        key, key_notes = _template_key(template, shadowed)
        name = str(template.get("Name") or key)[:400]
        choice = _choose_key(key, server, taken)
        if choice.key is None:
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
        chosen, key_note = choice.key, choice.note
        taken[chosen] = {IMPORT_TAG, _server_tag(server)}
        layout = layouts.get(template["LayoutTemplate"]) if template.get("LayoutTemplate") else None
        converted = convert_template(template, layout)
        notes = (*key_notes, *((key_note,) if key_note else ()), *converted.notes)
        email: dict[str, Any] = {"subject": converted.subject, "html": converted.html}
        if converted.text:
            email["text"] = converted.text
        created = create_template(
            context.team_id,
            context.created_by_id,
            {
                "name": name,
                "key": chosen,
                "description": " ".join(("Imported from Postmark.", *notes)),
                "type": "email",
                "content": {"templating": "liquid", "email": email},
                "tags": [IMPORT_TAG, _server_tag(server)],
            },
        )
        counts["needs_review" if notes else "created"] += 1
        items.append(
            ImportItem(label=name, status="created", url=f"/workflows/library/templates/{created.id}", notes=notes)
        )
    items += [
        ImportItem(
            label=f"{row.get('Name') or row.get('Alias')} (layout)",
            status="listed",
            notes=("PostHog has no layouts. Each template that uses this one has its own copy.",),
        )
        for row in layout_rows
    ]
    return SavedPage(imported=counts["created"] + counts["needs_review"], counts=dict(counts), items=tuple(items))


@frozen
class _KeyChoice:
    key: str | None
    note: str | None = None


def _choose_key(key: str, server: PostmarkServer, taken: dict[str, set[str]]) -> _KeyChoice:
    """A Postmark alias is only unique within a server, so a second server with the same alias gets a longer key."""
    if key not in taken:
        return _KeyChoice(key=key)
    tags = taken[key]
    if IMPORT_TAG not in tags or _server_tag(server) in tags:
        return _KeyChoice(key=None)
    longer = f"{key}-{server.id}"[:400]
    if longer in taken:
        return _KeyChoice(key=None)
    return _KeyChoice(
        key=longer, note=f"Another Postmark server has a template with the same alias, so the key is {longer}."
    )


def _fetch_domains(
    client: PostmarkClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    if client.kind != TokenKind.ACCOUNT:
        yield ImportPage(processed=0, save=_save_needs_account_token)
        return
    start = int(checkpoint.get("domains_offset", 0)) if checkpoint and "domains_offset" in checkpoint else 0
    if not checkpoint or "domains_offset" in checkpoint:
        for page, next_offset in client.offset_pages(
            "/domains", "Domains", {}, offset=start, count_param="count", offset_param="offset"
        ):
            details = [client.get(f"/domains/{domain['ID']}") for domain in page if domain.get("ID")]
            yield ImportPage(
                processed=len(page),
                save=partial(_save_domains, context, details),
                checkpoint={"domains_offset": next_offset} if next_offset is not None else {"senders_offset": 0},
            )
    senders_start = int(checkpoint.get("senders_offset", 0)) if checkpoint and "senders_offset" in checkpoint else 0
    for page, next_offset in client.offset_pages(
        "/senders", "SenderSignatures", {}, offset=senders_start, count_param="count", offset_param="offset"
    ):
        yield ImportPage(
            processed=len(page),
            save=partial(_save_senders, context, page),
            checkpoint={"senders_offset": next_offset} if next_offset is not None else None,
        )


def _save_needs_account_token() -> SavedPage:
    return SavedPage(
        imported=0,
        counts={"needs_account_token": 1},
        warnings=(
            "A server token can't read domains or sender signatures. Import this step with the account token, or add "
            "your domains in PostHog by hand.",
        ),
    )


def _senders(team_id: int) -> list[IntegrationRecord]:
    return list(IntegrationManager.email.credentials.list(team_id))


def _save_domains(context: ImportContext, domains: list[dict[str, Any]]) -> SavedPage:
    senders_by_domain: dict[str, list[IntegrationRecord]] = {}
    for sender in _senders(context.team_id):
        senders_by_domain.setdefault(str(sender.config.get("domain", "")).lower(), []).append(sender)
    items: list[ImportItem] = []
    counts: Counter[str] = Counter()
    for domain in domains:
        name = str(domain.get("Name") or "")
        senders = senders_by_domain.get(name.lower(), [])
        ready = any(sender.config.get("verified") for sender in senders)
        notes: list[str] = []
        if not ready:
            notes.append(
                "Waiting for DNS. Check the records on this domain's page."
                if senders
                else "Add this domain in PostHog to get its DNS records."
            )
        notes += _dns_notes(domain)
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


def _dns_notes(domain: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    if dkim_host := domain.get("DKIMHost"):
        notes.append(f"Keep the {dkim_host} TXT record while Postmark still sends for this domain.")
    return_path = str(domain.get("ReturnPathDomain") or "")
    if return_path.split(".")[0].lower() == MAIL_FROM_DEFAULT:
        notes.append(
            f"Postmark already uses {return_path} for bounces. Choose a different MAIL FROM subdomain in PostHog, or "
            "both tools will share one DNS name and one of them will break."
        )
    elif return_path:
        notes.append(f"Keep the {return_path} CNAME record while Postmark still sends for this domain.")
    return notes


def _save_senders(context: ImportContext, signatures: list[dict[str, Any]]) -> SavedPage:
    senders = {str(sender.config.get("email", "")).lower(): sender for sender in _senders(context.team_id)}
    items: list[ImportItem] = []
    for signature in signatures:
        address = str(signature.get("EmailAddress") or "")
        sender = senders.get(address.lower())
        notes: list[str] = []
        if sender is None:
            notes.append("Add this address as a sender in PostHog.")
        elif not sender.config.get("verified"):
            notes.append("This address is a PostHog sender but isn't verified yet.")
        if signature.get("Confirmed") is False:
            notes.append("This signature isn't confirmed in Postmark, so it can't send there.")
        if reply_to := signature.get("ReplyToEmailAddress"):
            notes.append(f"Postmark sends replies to {reply_to}. Set this reply-to on each email in PostHog.")
        items.append(
            ImportItem(
                label=f"{signature.get('Name') or address} <{address}>" if signature.get("Name") else address,
                status="listed",
                url=f"/workflows/channels/email/{sender.id}" if sender else "/workflows/channels",
                notes=tuple(notes),
            )
        )
    return SavedPage(imported=0, counts={"senders": len(signatures)}, items=tuple(items))


def _fetch_webhooks(
    client: PostmarkClient, context: ImportContext, checkpoint: StepCheckpoint | None
) -> Iterator[ImportPage]:
    importable = _importable_servers(client).importable
    after = _after_server(checkpoint)
    remaining = [server for server in importable if server.id > after]
    for index, server in enumerate(remaining):
        rows = client.for_server(server).get("/webhooks").get("Webhooks")
        if not isinstance(rows, list):
            raise PostmarkAPIError("Postmark sent an unexpected response for /webhooks.")
        yield ImportPage(
            processed=len(rows),
            save=partial(_save_webhooks, server, rows),
            checkpoint={"after_server": server.id} if index < len(remaining) - 1 else None,
        )


def _save_webhooks(server: PostmarkServer, webhooks: list[dict[str, Any]]) -> SavedPage:
    items = tuple(_webhook_item(server, webhook) for webhook in webhooks)
    return SavedPage(imported=0, counts={"listed": len(items)}, items=items)


def _webhook_item(server: PostmarkServer, webhook: dict[str, Any]) -> ImportItem:
    triggers = [
        name
        for name, config in (webhook.get("Triggers") or {}).items()
        if isinstance(config, dict) and config.get("Enabled")
    ]
    # A webhook URL or its auth can hold a secret, so only the host reaches the run's stored progress.
    host = urlparse(str(webhook.get("Url") or "")).hostname or "unknown host"
    return ImportItem(
        label=f"{server.name}: {webhook.get('MessageStream') or 'all streams'} to {host}",
        status="listed",
        notes=(f"Rebuild this webhook. It fires on: {', '.join(triggers) or 'nothing'}.",),
    )
