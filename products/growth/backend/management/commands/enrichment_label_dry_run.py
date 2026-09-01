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
    PromptConfigError,
    ai_processing_approved,
    classify_payload,
    get_active_config,
    recent_latest_fetches_qs,
    signup_domain_for_organization,
    validate_input_fields,
    validate_output_fields,
    verdict_field_key,
)
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig

_COMPANY_WIDTH = 30
_DOMAIN_WIDTH = 24
_MISSING = "-"
# Per output type, since a boolean verdict and a paragraph of reasoning need very different room.
_VALUE_WIDTHS = {"boolean": 8, "number": 6, "string": 40}


def _truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _cell(output: dict[str, Any], field: dict[str, str]) -> str:
    """Render one output key. A key the model never returned prints as absent rather than as a
    confident zero or empty string, which is what hardcoded key names used to produce."""
    if field["key"] not in output:
        return _MISSING
    value = output[field["key"]]
    if value == UNKNOWN:
        return "unknown"
    if value is None:
        return _MISSING
    if field["type"] == "boolean":
        return str(bool(value)).lower()
    if field["type"] == "number":
        try:
            return f"{float(value):.2f}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)


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
        try:
            validate_input_fields(config)
            validate_output_fields(config)
        except PromptConfigError as e:
            raise CommandError(str(e)) from e

        display_version = config.version
        if prompt_file:
            try:
                config.prompt_text = Path(prompt_file).read_text()
            except OSError as e:
                raise CommandError(f"Could not read --prompt-file {prompt_file}: {e}")
            # Never saved — an in-memory override for iteration, not a new version.
            display_version = f"{config.version}+file"

        # tenacity in labels.py already owns retries; the SDK's own internal retries underneath
        # would multiply that budget nine-fold per row.
        client = get_llm_client(product="growth").with_options(max_retries=0)
        # A custom output schema's pass/fail key differs from `label` - see
        # verdict_field_key's docstring.
        verdict_key = verdict_field_key(config)

        # Columns come from the schema, not from hardcoded key names: a config whose keys aren't
        # named confidence/reasoning used to print 0.00 and blanks as if they were the answer.
        compare_config: EnrichmentPromptConfig | None = None
        if compare_version:
            compare_config = EnrichmentPromptConfig.objects.filter(name=label, version=compare_version).first()
            if compare_config is None:
                raise CommandError(f"No config {compare_version!r} for label {label!r} to compare against")

        ordered_fetches = list(recent_latest_fetches_qs().select_related("organization")[:sample])

        column_widths = [_COMPANY_WIDTH, _DOMAIN_WIDTH]
        headers = ["Company", "Domain"]
        for field in config.output_fields:
            column_widths.append(_VALUE_WIDTHS.get(field["type"], _VALUE_WIDTHS["string"]))
            headers.append(field["key"])
        if compare_config is not None:
            for field in compare_config.output_fields:
                column_widths.append(_VALUE_WIDTHS.get(field["type"], _VALUE_WIDTHS["string"]))
                headers.append(f"prev.{field['key']}")
        row_fmt = "  ".join(f"{{:<{width}}}" for width in column_widths)

        self.stdout.write(f"Prompt version: {display_version}")
        self.stdout.write(row_fmt.format(*headers))

        classified = unknown = errors = skipped = 0
        for fetch in ordered_fetches:
            # Its own branch rather than an ERROR row: a declined org is a correct outcome, and
            # counting it as an error would trip the every-row-failed check below.
            if not ai_processing_approved(fetch.organization_id):
                skipped += 1
                row = [_truncate(fetch.organization.name, _COMPANY_WIDTH), _MISSING, "SKIPPED: no AI consent"]
                row += [_MISSING] * (len(headers) - len(row))
                self.stdout.write(row_fmt.format(*row))
                continue
            try:
                # Inside the guard too: an archived payload that isn't a dict (classify_payload
                # already tolerates this) must print one ERROR row, not kill the whole sample.
                company = fetch.payload.get("name") or fetch.organization.name
                signup_domain = signup_domain_for_organization(fetch.organization)
                output = classify_payload(config, fetch.payload, signup_domain, client)
            except Exception as e:
                errors += 1
                company = fetch.organization.name
                row = [_truncate(company, _COMPANY_WIDTH), _MISSING, f"ERROR: {_truncate(str(e), 40)}"]
                row += [_MISSING] * (len(headers) - len(row))
                self.stdout.write(row_fmt.format(*row))
                continue

            if verdict_key is not None and output.get(verdict_key) == UNKNOWN:
                unknown += 1
            else:
                classified += 1

            row = [
                _truncate(company, _COMPANY_WIDTH),
                _truncate(signup_domain, _DOMAIN_WIDTH) if signup_domain else _MISSING,
            ]
            row += [
                _truncate(_cell(output, field), _VALUE_WIDTHS.get(field["type"], _VALUE_WIDTHS["string"]))
                for field in config.output_fields
            ]
            if compare_config is not None:
                prior = (
                    EnrichmentLabelResult.objects.filter(
                        organization_id=fetch.organization_id, label_name=label, prompt_version=compare_version
                    )
                    .order_by("-created_at")
                    .first()
                )
                prior_output = prior.output if prior is not None else {}
                row += [
                    _truncate(_cell(prior_output, field), _VALUE_WIDTHS.get(field["type"], _VALUE_WIDTHS["string"]))
                    for field in compare_config.output_fields
                ]
            self.stdout.write(row_fmt.format(*row))

        summary = f"classified {classified}, unknown {unknown}, errors {errors}, skipped_no_ai_consent {skipped}"
        self.stdout.write(self.style.SUCCESS(summary) if errors == 0 else self.style.WARNING(summary))
        attempted = len(ordered_fetches) - skipped
        if attempted and errors == attempted:
            raise CommandError(f"every sampled row errored ({summary})")
