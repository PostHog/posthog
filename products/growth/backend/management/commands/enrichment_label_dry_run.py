"""Dry-run lab for iterating on an EnrichmentPromptConfig against real archived payloads.

Nothing here persists: this is the interactive loop for iterating on prompt/version
choices before a version is worth shadow-running for real via enrichment_label_batch.
"""

from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.llm.gateway_client import get_llm_client

from products.growth.backend.enrichment.labels import (
    UNKNOWN,
    classify_payload,
    get_active_config,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
)
from products.growth.backend.models import EnrichmentLabelResult

_COMPANY_WIDTH = 30
_DOMAIN_WIDTH = 24
_VERDICT_WIDTH = 8
_CONF_WIDTH = 6
_REASONING_WIDTH = 60


def _truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _verdict_str(value: Any) -> str:
    return "unknown" if value == UNKNOWN else str(bool(value)).lower()


class Command(BaseCommand):
    help = "Dry-run an EnrichmentPromptConfig against a sample of archived orgs without persisting anything."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--label", required=True, help="EnrichmentPromptConfig.name to run")
        parser.add_argument("--sample", type=int, default=50, help="Number of most-recently-fetched orgs to sample")
        parser.add_argument("--prompt-file", default=None, help="Override prompt_text from this file, in memory only")
        parser.add_argument("--compare-version", default=None, help="Show a prior version's stored verdicts alongside")

    def handle(self, *args: Any, **options: Any) -> None:
        label: str = options["label"]
        sample: int = options["sample"]
        if sample < 1:
            raise CommandError("--sample must be at least 1")
        prompt_file: str | None = options["prompt_file"]
        compare_version: str | None = options["compare_version"]

        config = get_active_config(label)
        if config is None:
            raise CommandError(f"No active EnrichmentPromptConfig for label {label!r}")

        display_version = config.version
        if prompt_file:
            try:
                config.prompt_text = Path(prompt_file).read_text()
            except OSError as e:
                raise CommandError(f"Could not read --prompt-file {prompt_file}: {e}")
            # Never saved — an in-memory override for iteration, not a new version.
            display_version = f"{config.version}+file"

        client = get_llm_client(product="growth")

        ordered_fetches = list(recent_latest_fetches_qs().select_related("organization")[:sample])

        column_widths = [_COMPANY_WIDTH, _DOMAIN_WIDTH, _VERDICT_WIDTH, _CONF_WIDTH, _REASONING_WIDTH]
        headers = ["Company", "Domain", "Verdict", "Conf", "Reasoning"]
        if compare_version:
            column_widths += [_VERDICT_WIDTH, _CONF_WIDTH]
            headers += ["Prev", "PrevConf"]
        row_fmt = "  ".join(f"{{:<{width}}}" for width in column_widths)

        self.stdout.write(f"Prompt version: {display_version}")
        self.stdout.write(row_fmt.format(*headers))

        classified = unknown = errors = 0
        for fetch in ordered_fetches:
            company = fetch.payload.get("name") or fetch.organization.name
            try:
                signup_domain = signup_domain_for_organization(fetch.organization)
                verdict = classify_payload(config, fetch.payload, signup_domain, client)
            except Exception as e:
                errors += 1
                row: list[str] = [
                    _truncate(company, _COMPANY_WIDTH),
                    "-",
                    "ERROR",
                    "-",
                    _truncate(str(e), _REASONING_WIDTH),
                ]
                if compare_version:
                    row += ["-", "-"]
                self.stdout.write(row_fmt.format(*row))
                continue

            label_verdict = verdict.get(label)
            if label_verdict == UNKNOWN:
                unknown += 1
            else:
                classified += 1

            row = [
                _truncate(company, _COMPANY_WIDTH),
                _truncate(signup_domain, _DOMAIN_WIDTH) if signup_domain else "-",
                _verdict_str(label_verdict),
                f"{verdict.get('confidence', 0.0):.2f}",
                _truncate(str(verdict.get("reasoning", "")), _REASONING_WIDTH),
            ]
            if compare_version:
                prior = (
                    EnrichmentLabelResult.objects.filter(
                        organization_id=fetch.organization_id, label_name=label, prompt_version=compare_version
                    )
                    .order_by("-created_at")
                    .first()
                )
                if prior is not None:
                    row += [_verdict_str(prior.output.get(label)), f"{prior.output.get('confidence', 0.0):.2f}"]
                else:
                    row += ["-", "-"]
            self.stdout.write(row_fmt.format(*row))

        summary = f"classified {classified}, unknown {unknown}, errors {errors}"
        self.stdout.write(self.style.SUCCESS(summary) if errors == 0 else self.style.WARNING(summary))
