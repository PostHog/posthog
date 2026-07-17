#!/usr/bin/env python3
"""Prune property definitions from a PostHog project by name or regex.

Finds property definitions (the rows behind Data Management > Properties) matching a literal
list of names or a regex, then deletes them. That list only ever grows - PostHog never
auto-removes definitions - so this is how erroneous or deprecated ones get cleaned up.

Discovery pages through the property definitions API
(https://posthog.com/docs/api/property-definitions) for the chosen --type, then filters:
literal names match exactly, --regex matches unanchored (like PostgreSQL `~`; anchor with
^/$). Built-in virtual properties (e.g. $virt_*) are skipped - they aren't real rows and
can't be deleted.

Pruning deletes one definition per request via
`DELETE /api/projects/:id/property_definitions/:id/`. It removes only the Postgres row that
backs the Properties list; it does not touch event-property mappings or the ClickHouse
`property_definitions` mirror. A definition reappears if its property is still seen on
incoming events, so fix the source instrumentation first. For a full server-side bulk
cleanup (Postgres + event properties + ClickHouse), use the `cleanup-property-definitions`
Temporal workflow instead.

Usage:
  export POSTHOG_PERSONAL_API_KEY=phx_...   # needs property_definition:read and :write
  python products/support/scripts/prune_property_definitions.py temp_prop other_prop \\
      --host eu --project-id 123 --type event --dry-run
  python products/support/scripts/prune_property_definitions.py \\
      --regex '^temp_' --host eu --project-id 123 --type event --dry-run

--host accepts a full instance URL or the PostHog Cloud region shorthands us/eu.

When a personal API key can't be created (e.g. an impersonated staff session), pass a
browser session instead: --session-id (env POSTHOG_SESSION_ID) with the value of the
`sessionid` cookie from devtools. The script fetches a CSRF token automatically, and
before running anything - reads included - requires typing the authenticated user's
email, so acting on behalf of an impersonated user is always a conscious choice.
"""

# ruff: noqa: T201 allow print statements in this CLI script

import os
import re
import sys
import json
import time
import argparse
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests

MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 2.0
REGION_HOSTS = {"us": "https://us.posthog.com", "eu": "https://eu.posthog.com"}


def resolve_host(value: str) -> str:
    """Map a region shorthand ('us'/'eu', any case) to its Cloud host; pass explicit hosts through."""
    return REGION_HOSTS.get(value.strip().lower(), value).rstrip("/")


class PruneError(Exception):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr)


def request_with_retries(
    session: requests.Session, method: str, url: str, max_retries: int = MAX_RETRIES, **kwargs: Any
) -> requests.Response:
    """Issue a request, retrying on 429 (honoring Retry-After) and 5xx with backoff."""
    last_error = ""
    for attempt in range(max_retries):
        try:
            response = session.request(method, url, timeout=60, **kwargs)
        except requests.RequestException as err:
            last_error = str(err)
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", BACKOFF_BASE_SECONDS * 2**attempt))
            log(f"  rate limited, retrying in {retry_after:.0f}s...")
            time.sleep(retry_after)
            continue
        if response.status_code >= 500:
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            time.sleep(BACKOFF_BASE_SECONDS * 2**attempt)
            continue
        return response
    raise PruneError(f"{method} {url} failed after {max_retries} attempts: {last_error}")


def confirm_acting_user(email: str) -> None:
    """Make the operator type the session's email so the acting-as identity is conscious, not assumed."""
    log("Session auth acts as the browser session's logged-in user - including for read queries.")
    try:
        entered = input("Enter that user's email to confirm you know who you're acting as: ")
    except EOFError as err:
        raise PruneError(
            "Session auth requires interactively confirming the authenticated user; "
            "use a personal API key for non-interactive runs."
        ) from err
    if entered.strip().lower() != email.strip().lower():
        raise PruneError(
            "That does not match the session's authenticated user - check whose session this is "
            "(e.g. the impersonated user in your browser) and rerun."
        )


def setup_session_auth(session: requests.Session, host: str, session_id: str) -> None:
    """Authenticate with a browser session cookie (works for impersonated staff sessions).

    Django session auth requires a CSRF token on unsafe methods, so fetch the CSRF cookie
    from the login page and mirror it into the X-CSRFToken header, with the host as Referer.
    Before anything runs - reads included - the operator must type the authenticated user's
    email to confirm they know who the session acts as.
    """
    session.cookies.set("sessionid", session_id)
    request_with_retries(session, "GET", f"{host}/login")
    csrf_token = session.cookies.get("posthog_csrftoken")
    if not csrf_token:
        raise PruneError(f"Could not obtain a CSRF cookie from {host}/login - is this a PostHog instance?")
    session.headers["X-CSRFToken"] = csrf_token
    session.headers["Referer"] = f"{host}/"

    me = request_with_retries(session, "GET", f"{host}/api/users/@me/")
    if me.status_code != 200:
        raise PruneError(
            f"Session auth failed (HTTP {me.status_code}) - is the sessionid cookie value current? "
            "Impersonated sessions expire when the impersonation ends or times out."
        )
    email = me.json().get("email")
    if not email:
        raise PruneError("Could not determine the session's authenticated user")
    confirm_acting_user(email)
    log(f"Authenticated via session as {email}")


def iter_property_definitions(
    session: requests.Session,
    host: str,
    project_id: str,
    prop_type: str,
    group_type_index: Optional[int],
    page_size: int,
    names: Optional[list[str]] = None,
) -> Iterator[dict[str, Any]]:
    """Page through the property definitions list API for the given type.

    When `names` is supplied, the API filters server-side (names mode); otherwise the whole
    type is scanned so a regex can be matched client-side.
    """
    params: dict[str, str] = {"type": prop_type, "limit": str(page_size)}
    if group_type_index is not None:
        params["group_type_index"] = str(group_type_index)
    if names:
        params["properties"] = ",".join(names)
    url: Optional[str] = f"{host}/api/projects/{project_id}/property_definitions/?{urlencode(params)}"
    page = 0
    while url:
        response = request_with_retries(session, "GET", url)
        if response.status_code != 200:
            raise PruneError(f"Property definitions query failed (HTTP {response.status_code}): {response.text[:500]}")
        data = response.json()
        page += 1
        log(f"  page {page}: {len(data['results'])} definitions")
        yield from data["results"]
        url = data.get("next")


def is_deletable(definition: dict[str, Any]) -> bool:
    """Built-in virtual properties (e.g. $virt_* revenue) aren't real rows and can't be deleted."""
    return not definition.get("virtual") and not str(definition.get("id", "")).startswith("$builtin_")


def find_matching_definitions(
    definitions: list[dict[str, Any]], names: list[str], regex: Optional[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Filter definitions to those matching the literal names or the regex.

    Returns (matched, not_found_names). not_found_names is only meaningful in names mode: the
    requested names that have no property definition (already gone, or never existed).
    """
    deletable = [d for d in definitions if is_deletable(d)]
    if regex is not None:
        compiled = re.compile(regex)
        return [d for d in deletable if compiled.search(d["name"])], []
    names_set = set(names)
    matched = [d for d in deletable if d["name"] in names_set]
    not_found = sorted(names_set - {d["name"] for d in matched})
    return matched, not_found


def prune_definitions(
    session: requests.Session, host: str, project_id: str, matched: list[dict[str, Any]]
) -> tuple[int, list[str]]:
    """Delete each matched definition. Returns (deleted, failures)."""
    failures: list[str] = []
    deleted = 0
    total = len(matched)
    for index, definition in enumerate(matched, start=1):
        url = f"{host}/api/projects/{project_id}/property_definitions/{definition['id']}/"
        try:
            response = request_with_retries(session, "DELETE", url)
        except PruneError as err:
            failures.append(f"{definition['name']} ({definition['id']}): {err}")
        else:
            if response.status_code == 204:
                deleted += 1
            else:
                failures.append(
                    f"{definition['name']} ({definition['id']}): HTTP {response.status_code} {response.text[:200]}"
                )
        if index % 50 == 0 or index == total:
            log(f"  {index}/{total} delete requests done")
    return deleted, failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prune property definitions matching names or a regex from a PostHog project.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("names", nargs="*", help="Literal property definition names to prune (exact match)")
    parser.add_argument(
        "--regex",
        default=None,
        help="Regex matched unanchored against property names, e.g. '^temp_' - anchor with ^/$ to bound it",
    )
    parser.add_argument(
        "--type",
        dest="prop_type",
        choices=["event", "person", "group", "session"],
        default="event",
        help="Which property definitions to prune",
    )
    parser.add_argument(
        "--group-type-index", type=int, default=None, help="Group type index (required when --type group)"
    )
    # Env-backed args resolve after parsing so --help never prints API keys from the environment
    parser.add_argument(
        "--host",
        default=None,
        help="PostHog instance URL, or region shorthand 'us'/'eu' for PostHog Cloud "
        "(env: POSTHOG_HOST, else https://us.posthog.com)",
    )
    parser.add_argument("--project-id", default=None, help="Numeric project ID (env: POSTHOG_PROJECT_ID)")
    parser.add_argument(
        "--personal-api-key",
        default=None,
        help="Personal API key (phx_...) with property_definition:read and property_definition:write "
        "(env: POSTHOG_PERSONAL_API_KEY)",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Browser `sessionid` cookie value, as an alternative to --personal-api-key "
        "(e.g. for impersonated staff sessions; env: POSTHOG_SESSION_ID)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be pruned; change nothing")
    parser.add_argument("--page-size", type=int, default=500, help="Definitions fetched per page when scanning")
    parser.add_argument("--output", help="Write the matched definitions report to this JSON file")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip the confirmation prompt")
    args = parser.parse_args()

    args.host = resolve_host(args.host or os.environ.get("POSTHOG_HOST") or "https://us.posthog.com")
    args.project_id = args.project_id or os.environ.get("POSTHOG_PROJECT_ID")
    args.personal_api_key = args.personal_api_key or os.environ.get("POSTHOG_PERSONAL_API_KEY")
    args.session_id = args.session_id or os.environ.get("POSTHOG_SESSION_ID")

    if bool(args.names) == bool(args.regex):
        parser.error("provide either positional names or --regex (exactly one)")
    if not args.project_id:
        parser.error("--project-id (or POSTHOG_PROJECT_ID) is required")
    if not args.personal_api_key and not args.session_id:
        parser.error(
            "either --personal-api-key (POSTHOG_PERSONAL_API_KEY) or --session-id (POSTHOG_SESSION_ID) is required"
        )
    if args.prop_type == "group" and args.group_type_index is None:
        parser.error("--group-type-index is required when --type group")
    if args.prop_type != "group" and args.group_type_index is not None:
        parser.error("--group-type-index can only be set when --type group")
    if args.regex is not None:
        try:
            re.compile(args.regex)
        except re.error as err:
            parser.error(f"invalid --regex: {err}")
    return args


def main() -> int:
    args = parse_args()
    names = sorted(set(args.names))

    session = requests.Session()
    if args.personal_api_key:
        session.headers["Authorization"] = f"Bearer {args.personal_api_key}"
    else:
        setup_session_auth(session, args.host, args.session_id)

    match_desc = f"regex /{args.regex}/" if args.regex else f"{len(names)} name(s)"
    log(f"Scanning {args.prop_type} property definitions in project {args.project_id} matching {match_desc}")
    definitions = list(
        iter_property_definitions(
            session,
            args.host,
            args.project_id,
            args.prop_type,
            args.group_type_index,
            args.page_size,
            names=names or None,
        )
    )
    matched, not_found = find_matching_definitions(definitions, names, args.regex)
    matched = sorted(matched, key=lambda d: d["name"])

    log("")
    log(f"Matched {len(matched)} property definition(s) to prune (scanned {len(definitions)}).")

    if not_found:
        log("")
        log(f"Not found - nothing to prune ({len(not_found)}; already absent or never existed):")
        for name in not_found:
            log(f"  {name}")

    if args.output:
        with open(args.output, "w") as f:
            json.dump(
                {
                    "type": args.prop_type,
                    "regex": args.regex,
                    "names": names,
                    "matched_definitions": matched,
                    "not_found_names": not_found,
                },
                f,
                indent=2,
            )
        log(f"Wrote report to {args.output}")

    if not matched:
        log("Nothing to prune.")
        return 0

    preview = matched[:10]
    log("")
    log("Sample of definitions that would be pruned:")
    for definition in preview:
        log(f"  {definition['id']}  {definition['name']}  ({definition.get('property_type') or 'unknown type'})")
    if len(matched) > len(preview):
        log(f"  ... and {len(matched) - len(preview)} more (use --output to save the full list)")

    log("")
    log(
        "Note: a pruned definition reappears if the property is still present on incoming events - "
        "fix the source instrumentation first. This removes only the definition backing "
        "Data Management > Properties, not event-property mappings or the ClickHouse mirror."
    )

    if args.dry_run:
        log("")
        log("DRY RUN: no changes made.")
        return 0

    if not args.yes:
        prompt = (
            f"\nAbout to permanently delete {len(matched)} {args.prop_type} property definitions "
            f"from project {args.project_id}. Type 'prune' to continue: "
        )
        if input(prompt).strip().lower() != "prune":
            log("Aborted.")
            return 1

    deleted, failures = prune_definitions(session, args.host, args.project_id, matched)
    log("")
    log(f"Done: deleted {deleted}/{len(matched)} property definitions, {len(failures)} failures.")
    for failure in failures[:20]:
        log(f"  FAILED: {failure}")
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PruneError as err:
        log(f"Error: {err}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("\nInterrupted.")
        sys.exit(130)
