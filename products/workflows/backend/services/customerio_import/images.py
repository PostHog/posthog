"""Copies the images an imported Customer.io email shows into the team's email media library.

Customer.io serves email images from its own asset hosts, so they stop loading once the team closes its account.
`email_images` reads only those hosts.
"""

import re
import html
from typing import Any

from posthog.models import Team, User

from products.workflows.backend.facade.contracts import EmailImageSource, ImageBudget, ImportNote, RehostedWorkflow
from products.workflows.backend.facade.enums import WorkflowImportNoteLevel
from products.workflows.backend.services.email_images import copy_images

CUSTOMERIO_IMAGES = EmailImageSource(key="customerio", label="Customer.io", host_suffixes=("customeriomail.com",))

# ASCII only, so a lookalike Unicode host can't match. `copy_images` checks the host again after unescaping.
# An unquoted CSS `url(...)` ends at its closing parenthesis, and more CSS can follow. Anywhere else a parenthesis is
# part of the URL. A quote written as an entity, like `url(&quot;...&quot;)`, ends both.
_ASSET_HOST = r"https://[a-z0-9-]+\.customeriomail\.com/"
_AMPERSAND = r"&(?!(?:quot|apos|#0*3[49]|#x0*2[27]);)"
_ASSET_URL = re.compile(
    rf"(?:(?<=url\()|(?<=url\( )){_ASSET_HOST}(?:[^\s\"'<>()&]|{_AMPERSAND}|\([^\s\"'<>()]*\))*"
    rf"|{_ASSET_HOST}(?:[^\s\"'<>&]|{_AMPERSAND})*",
    re.IGNORECASE | re.ASCII,
)
_LINK_ATTRIBUTE = re.compile(r"href\s*=\s*[\"']?$", re.IGNORECASE)


def rehost_images(
    team: Team, user: User, workflow: dict[str, Any], dry_run: bool, budget: ImageBudget
) -> RehostedWorkflow:
    """The workflow with every Customer.io-hosted email image pointing at a copy in the media library."""
    urls_by_step = {
        action["id"]: list(dict.fromkeys(_asset_urls(body)))
        for action in workflow["actions"]
        if (body := _html(action)) is not None
    }
    all_urls = list(dict.fromkeys(url for urls in urls_by_step.values() for url in urls))
    if not all_urls:
        return RehostedWorkflow(workflow=workflow, notes=())
    count = len({html.unescape(url) for url in all_urls})
    if not budget.can_upload:
        return RehostedWorkflow(
            workflow=workflow,
            notes=(
                ImportNote(
                    level=WorkflowImportNoteLevel.NEEDS_INPUT,
                    message=f"{count} email {_images(count)} still {_load(count)} from Customer.io's servers, "
                    "because this import can't write to the media library. The person importing needs editor "
                    "access to it, and their API key or PostHog MCP connection needs the uploaded_media:write "
                    "scope. Reconnect the MCP and allow uploading media, then import again, or upload "
                    f"{_them(count)} before you close your Customer.io account.",
                ),
            ),
        )
    if dry_run:
        return RehostedWorkflow(
            workflow=workflow,
            notes=(
                ImportNote(
                    level=WorkflowImportNoteLevel.APPROXIMATED,
                    message=f"{count} email {_images(count)} on Customer.io's servers will be "
                    "copied into your email media library when you import.",
                ),
            ),
        )

    copied = _copy_images(team, user, all_urls, budget)
    notes: list[ImportNote] = []
    actions = []
    for action in workflow["actions"]:
        body = _html(action)
        if body is None:
            actions.append(action)
            continue
        # One pass over whole matches, so a URL that starts with another copied URL keeps its own copy.
        body = _ASSET_URL.sub(lambda match: _replace(match, copied), body)
        actions.append(_with_html(action, body))
        missed = [url for url in urls_by_step.get(action["id"], []) if url not in copied]
        if missed:
            notes.append(
                ImportNote(
                    level=WorkflowImportNoteLevel.NEEDS_INPUT,
                    message=f"{len(missed)} {_images(len(missed))} could not be copied from Customer.io and still "
                    f"{_load(len(missed))} from its servers: {', '.join(missed[:3])}{'…' if len(missed) > 3 else ''}. "
                    f"Upload {_them(len(missed))} to the media library before you close your Customer.io account.",
                    step_id=action["id"],
                    step_name=action.get("name"),
                )
            )
    return RehostedWorkflow(workflow={**workflow, "actions": actions}, notes=tuple(notes))


def _copy_images(team: Team, user: User, urls: list[str], budget: ImageBudget) -> dict[str, str]:
    # Browsers read `&amp;` in an attribute as `&`, so the request has to as well. Spellings of one image share a copy.
    sources = {url: html.unescape(url) for url in urls}
    copies = copy_images(team, user, dict.fromkeys(sources.values()), CUSTOMERIO_IMAGES, budget)
    return {url: copies[source] for url, source in sources.items() if source in copies}


def _asset_urls(body: str) -> list[str]:
    return [
        url
        for match in _ASSET_URL.finditer(body)
        if not _is_link(match) and (url := _trimmed(match.group(0))) is not None
    ]


def _is_link(match: re.Match[str]) -> bool:
    # A link to a Customer.io asset, like a PDF, is not an image the email shows.
    return _LINK_ATTRIBUTE.search(match.string, max(0, match.start() - 20), match.start()) is not None


def _trimmed(found: str) -> str | None:
    """The image URL in a match, or None for a URL built with Liquid, whose real address only exists at send time."""
    # A parenthesis is part of the URL unless it closes one around it.
    end, extra_closing = len(found), found.count(")") - found.count("(")
    while extra_closing > 0 and end > 0 and found[end - 1] == ")":
        end -= 1
        extra_closing -= 1
    url = found[:end]
    return None if "{" in url else url


def _replace(match: re.Match[str], copied: dict[str, str]) -> str:
    found = match.group(0)
    url = None if _is_link(match) else _trimmed(found)
    if url is None or url not in copied:
        return found
    return copied[url] + found[len(url) :]


def _html(action: dict[str, Any]) -> str | None:
    if action.get("type") != "function_email":
        return None
    value = (((action.get("config") or {}).get("inputs") or {}).get("email") or {}).get("value") or {}
    body = value.get("html")
    return body if isinstance(body, str) else None


def _with_html(action: dict[str, Any], body: str) -> dict[str, Any]:
    config = action["config"]
    email = config["inputs"]["email"]
    # The design is built from the HTML when the draft is checked, so it is dropped and built again from the copies.
    value = {key: item for key, item in email["value"].items() if key != "design"}
    return {
        **action,
        "config": {
            **config,
            "inputs": {**config["inputs"], "email": {**email, "value": {**value, "html": body}}},
        },
    }


def _images(count: int) -> str:
    return "image" if count == 1 else "images"


def _load(count: int) -> str:
    return "loads" if count == 1 else "load"


def _them(count: int) -> str:
    return "it" if count == 1 else "them"
