from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from products.growth.backend.facade import api, contracts

_COMPANY_WIDTH = 30
_DOMAIN_WIDTH = 24
_MISSING = "-"
# Per output type, since a boolean verdict and a paragraph of reasoning need very different room.
_VALUE_WIDTHS = {"boolean": 8, "number": 6, "string": 40}


def _truncate(value: str, width: int) -> str:
    return value if len(value) <= width else value[: width - 1] + "…"


def _width(field: contracts.LabelOutputField) -> int:
    return _VALUE_WIDTHS.get(field.type, _VALUE_WIDTHS["string"])


def _cell(output: dict[str, Any], field: contracts.LabelOutputField) -> str:
    """Render one output key. A key the model never returned prints as absent rather than as a
    confident zero or empty string, which is what hardcoded key names used to produce."""
    if field.key not in output:
        return _MISSING
    value = output[field.key]
    if value == contracts.UNKNOWN:
        return "unknown"
    if value is None:
        return _MISSING
    if field.type == "boolean":
        return str(bool(value)).lower()
    if field.type == "number":
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

        try:
            run = api.iter_label_dry_run(label, sample=sample, prompt_file=prompt_file, compare_version=compare_version)
        except contracts.LabelPromptFileUnreadable as e:
            raise CommandError(f"Could not read --prompt-file {e.path}: {e.error}")
        except contracts.GrowthEnrichmentError as e:
            raise CommandError(str(e)) from e

        # Columns come from the schema, not from hardcoded key names: a config whose keys aren't
        # named confidence/reasoning used to print 0.00 and blanks as if they were the answer.
        column_widths = [_COMPANY_WIDTH, _DOMAIN_WIDTH]
        headers = ["Company", "Domain"]
        for field in run.output_fields:
            column_widths.append(_width(field))
            headers.append(field.key)
        if run.compare_output_fields is not None:
            for field in run.compare_output_fields:
                column_widths.append(_width(field))
                headers.append(f"prev.{field.key}")
        row_fmt = "  ".join(f"{{:<{width}}}" for width in column_widths)

        self.stdout.write(f"Prompt version: {run.display_version}")
        self.stdout.write(row_fmt.format(*headers))

        sampled = classified = unknown = errors = skipped = 0
        for item in run.rows:
            sampled += 1
            # Its own branch rather than an ERROR row: a declined org is a correct outcome, and
            # counting it as an error would trip the every-row-failed check below.
            if item.skipped_no_ai_consent:
                skipped += 1
                row = [_truncate(item.company, _COMPANY_WIDTH), _MISSING, "SKIPPED: no AI consent"]
                row += [_MISSING] * (len(headers) - len(row))
                self.stdout.write(row_fmt.format(*row))
                continue
            if item.error is not None:
                errors += 1
                row = [_truncate(item.company, _COMPANY_WIDTH), _MISSING, f"ERROR: {_truncate(item.error, 40)}"]
                row += [_MISSING] * (len(headers) - len(row))
                self.stdout.write(row_fmt.format(*row))
                continue

            output = item.output or {}
            if run.verdict_key is not None and output.get(run.verdict_key) == contracts.UNKNOWN:
                unknown += 1
            else:
                classified += 1

            row = [
                _truncate(item.company, _COMPANY_WIDTH),
                _truncate(item.signup_domain, _DOMAIN_WIDTH) if item.signup_domain else _MISSING,
            ]
            row += [_truncate(_cell(output, field), _width(field)) for field in run.output_fields]
            if run.compare_output_fields is not None:
                prior_output = item.prior_output or {}
                row += [_truncate(_cell(prior_output, field), _width(field)) for field in run.compare_output_fields]
            self.stdout.write(row_fmt.format(*row))

        summary = f"classified {classified}, unknown {unknown}, errors {errors}, skipped_no_ai_consent {skipped}"
        self.stdout.write(self.style.SUCCESS(summary) if errors == 0 else self.style.WARNING(summary))
        attempted = sampled - skipped
        if attempted and errors == attempted:
            raise CommandError(f"every sampled row errored ({summary})")
