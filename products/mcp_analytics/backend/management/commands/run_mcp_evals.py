"""Run agent eval scenarios against a live MCP server and write every trial to a JSON report.

Each scenario's intent goes through a Claude tool-use loop against the server, ``--trials``
times. The report keeps each trial's outcome, tool calls with full results, tokens and latency.
Nothing here grades the trials.

The server's bearer token comes from ``MCP_EVAL_SERVER_TOKEN`` so it never appears in the
process list. An ``Authorization`` header passed with ``--header`` takes precedence. Against
PostHog's own server, pin the project with ``--header 'x-posthog-project-id: <id>'``, because
PostHog keeps the active project per token, so one trial's project switch moves the others.
"""

import os
import re
import asyncio
from pathlib import Path
from typing import cast, get_args
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import anthropic

from products.mcp_analytics.backend.agent_evals.runner import (
    Effort,
    RunConfig,
    describe_failure,
    format_run_summary,
    quiet_transport_logs,
    run_agent_evals,
)
from products.mcp_analytics.backend.agent_evals.scenarios import load_scenarios

TOKEN_ENV = "MCP_EVAL_SERVER_TOKEN"


class Command(BaseCommand):
    help = "Run agent eval scenarios against a live MCP server and write a JSON report."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--url", required=True, help="The MCP endpoint, for example http://localhost:8787/mcp.")
        parser.add_argument("--scenarios", type=Path, required=True, help="YAML file of scenarios to run.")
        parser.add_argument("--out", type=Path, required=True, help="Where to write the JSON report.")
        parser.add_argument(
            "--header", action="append", default=[], help="Extra request header as 'Name: value'. Repeatable."
        )
        parser.add_argument("--only", action="append", default=[], help="Run only this scenario id. Repeatable.")
        parser.add_argument("--trials", type=int, default=3)
        parser.add_argument("--concurrency", type=int, default=4)
        parser.add_argument("--model", default="claude-opus-5-5")
        parser.add_argument(
            "--effort", choices=get_args(Effort), help="Omitted unless set; the model's default applies."
        )
        parser.add_argument("--max-turns", type=int, default=20)

    def handle(self, *args: object, **options: object) -> None:
        if not settings.ANTHROPIC_API_KEY:
            raise CommandError("ANTHROPIC_API_KEY is not set")
        for name in ("trials", "concurrency", "max_turns"):
            if cast(int, options[name]) <= 0:
                raise CommandError(f"--{name.replace('_', '-')} must be a positive integer")

        scenario_file = load_scenarios(cast(Path, options["scenarios"]))
        only = cast(list[str], options["only"])
        unknown = sorted(set(only) - {scenario.id for scenario in scenario_file.scenarios})
        if unknown:
            raise CommandError(f"unknown scenario ids: {', '.join(unknown)}")
        scenarios = tuple(scenario for scenario in scenario_file.scenarios if not only or scenario.id in only)

        config = RunConfig(
            url=_url(cast(str, options["url"])),
            headers=_headers(cast(list[str], options["header"]), os.environ.get(TOKEN_ENV)),
            scenarios=scenarios,
            trials=cast(int, options["trials"]),
            concurrency=cast(int, options["concurrency"]),
            model=cast(str, options["model"]),
            effort=cast(Effort | None, options["effort"]),
            max_turns=cast(int, options["max_turns"]),
        )
        try:
            with quiet_transport_logs():
                report = asyncio.run(
                    run_agent_evals(config, anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY))
                )
        except Exception as unreachable:
            # Only the catalog session raises here; every trial failure stays inside its trial.
            raise CommandError(f"could not list the server's tools: {describe_failure(unreachable, config)}") from None

        out = cast(Path, options["out"])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.to_json())
        self.stdout.write(f"{format_run_summary(report)}\nwrote {out}")


def _url(raw: str) -> str:
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise CommandError("--url must be an http or https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        # Credentials travel in a header, which never reaches the report or the logs.
        raise CommandError(f"--url must have no credentials or query; use {TOKEN_ENV} or --header")
    return raw


def _headers(raw_headers: list[str], token: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for raw in raw_headers:
        name, separator, value = raw.partition(":")
        if not separator or not name.strip():
            raise CommandError("--header must look like 'Name: value'")
        headers[name.strip()] = _header_value(name.strip(), value)
    if token and not any(name.lower() == "authorization" for name in headers):
        headers["Authorization"] = f"Bearer {_header_value(TOKEN_ENV, token)}"
    return headers


def _header_value(source: str, value: str) -> str:
    # Checked here so the HTTP client never rejects it, because its error would quote the value.
    value = value.strip()
    if _CONTROL_CHARACTERS.search(value):
        raise CommandError(f"{source} contains a control character")
    return value


_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
