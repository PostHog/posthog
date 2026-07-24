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

import os
import re
import sys
import json
import argparse
from collections import Counter
from collections.abc import Iterator
from typing import Any, Optional
from urllib.parse import urlencode

import requests
from lib.console import confirm, format_status_counts, log, printable
from lib.errors import PostHogScriptError
from lib.posthog_api import request_with_retries, resolve_host, setup_session_auth


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
    # The API splits `properties` on commas, so a name containing one can't be filtered
    # server-side; fall back to a full scan and let the client-side exact match handle it.
    if names and not any("," in name for name in names):
        params["properties"] = ",".join(names)
    url: Optional[str] = f"{host}/api/projects/{project_id}/property_definitions/?{urlencode(params)}"
    page = 0
    while url:
        response = request_with_retries(session, "GET", url)
        if response.status_code != 200:
            raise PostHogScriptError(
                f"Property definitions query failed (HTTP {response.status_code}): {response.text[:500]}"
            )
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
    session: requests.Session, host: str, project_id: str, matched: list[dict[str, Any]], batch_size: int
) -> tuple[Counter[str], list[str]]:
    """Delete each matched definition, one request per id (there is no bulk delete endpoint).

    Returns (status_counts, failures). status_counts is keyed by HTTP status code (as a
    string), plus an "error" bucket for requests that never got a response; only a 2xx is
    counted as a successful delete. A read-only session/key returns 403, and field-level
    access control can make some deletes 403 while others succeed, so outcomes are reported
    as a per-batch status-code histogram rather than assumed uniform.
    """
    status_counts: Counter[str] = Counter()
    failures: list[str] = []
    total = len(matched)
    batch_counts: Counter[str] = Counter()
    batch_start = 1
    for index, definition in enumerate(matched, start=1):
        url = f"{host}/api/projects/{project_id}/property_definitions/{definition['id']}/"
        try:
            response = request_with_retries(session, "DELETE", url)
        except PostHogScriptError as err:
            status_counts["error"] += 1
            batch_counts["error"] += 1
            failures.append(f"{definition['name']} ({definition['id']}): {err}")
        else:
            code = response.status_code
            status_counts[str(code)] += 1
            batch_counts[str(code)] += 1
            if not 200 <= code < 300:
                failures.append(f"{definition['name']} ({definition['id']}): HTTP {code} {response.text[:200]}")
        if index % batch_size == 0 or index == total:
            log(f"  deletes {batch_start}-{index} of {total}: {format_status_counts(batch_counts)}")
            batch_counts = Counter()
            batch_start = index + 1
    return status_counts, failures


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
    parser.add_argument(
        "--batch-size", type=int, default=50, help="How many deletes to group per reported status-code batch"
    )
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
    if args.batch_size <= 0:
        parser.error("--batch-size must be greater than zero")
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
            log(f"  {printable(name)}")

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
        log(
            f"  {definition['id']}  {printable(definition['name'])}  ({definition.get('property_type') or 'unknown type'})"
        )
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
        if not confirm(
            prompt, "prune", eof_message="Confirmation requires interactive input; pass --yes for non-interactive runs."
        ):
            log("Aborted.")
            return 1

    status_counts, failures = prune_definitions(session, args.host, args.project_id, matched, args.batch_size)
    deleted = sum(n for code, n in status_counts.items() if code.isdigit() and 200 <= int(code) < 300)
    log("")
    log(f"Done: {deleted}/{len(matched)} deleted. Status breakdown: {format_status_counts(status_counts)}")
    forbidden = status_counts.get("403", 0)
    if forbidden:
        log(
            f"  {forbidden} forbidden (HTTP 403): the credential can't delete these - a read-only "
            "session/key, or field-level access control on restricted properties."
        )
    for failure in failures[:20]:
        log(f"  FAILED: {printable(failure)}")
    if len(failures) > 20:
        log(f"  ... and {len(failures) - 20} more failures")
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except PostHogScriptError as err:
        log(f"Error: {printable(str(err))}")
        sys.exit(1)
    except KeyboardInterrupt:
        log("\nInterrupted.")
        sys.exit(130)
