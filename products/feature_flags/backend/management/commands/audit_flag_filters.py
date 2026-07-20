"""Read-only audit of `FeatureFlag.filters` against the #50084 structural + cross-field rules.

Reports violations grouped by rule, plus a frequency table of unknown keys that enforcement
would drop. A clean run (zero violations) is the gate for flipping enforcement on; unknown
keys are informational (they get dropped silently by design). Contextual rules (cohort
existence, circular dependencies, size limits, feature gates) are already enforced at write
time in FeatureFlagSerializer and are not audited.

Each flag costs a DRF serializer instantiation, so a full prod scan takes minutes, not
seconds — it's an offline command.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from products.feature_flags.backend.api.filters_schema import LEGACY_UNKNOWN_FILTER_KEYS
from products.feature_flags.backend.filters_validation import collect_filters_violations
from products.feature_flags.backend.models.feature_flag import FeatureFlag


@dataclass
class RuleReport:
    rule_id: str
    flags_affected: int = 0
    total_violations: int = 0
    sample_flag_ids: list[int] = field(default_factory=list)
    sample_details: list[str] = field(default_factory=list)


class UnknownKeyAggregator:
    """Implements the UnknownKeySink protocol; counts flags affected per (level, key)."""

    def __init__(self, max_samples: int) -> None:
        self.max_samples = max_samples
        self.flag_counts: dict[tuple[str, str], int] = {}
        self.sample_flag_ids: dict[tuple[str, str], list[int]] = {}
        self._current_flag_id: int | None = None
        self._seen_for_current_flag: set[tuple[str, str]] = set()

    def record(self, *, level: str, keys: Sequence[str], flag_id: int | None) -> None:
        # Flags are scanned sequentially, so dedupe per (level, key) within the current flag —
        # the same unknown key across several groups of one flag counts that flag once.
        if flag_id != self._current_flag_id:
            self._current_flag_id = flag_id
            self._seen_for_current_flag = set()
        for key in keys:
            pair = (level, key)
            if pair in self._seen_for_current_flag:
                continue
            self._seen_for_current_flag.add(pair)
            self.flag_counts[pair] = self.flag_counts.get(pair, 0) + 1
            samples = self.sample_flag_ids.setdefault(pair, [])
            if flag_id is not None and len(samples) < self.max_samples:
                samples.append(flag_id)


class Command(BaseCommand):
    help = (
        "Read-only audit of FeatureFlag.filters (all flags, soft-deleted included) against the "
        "#50084 structural + cross-field rules. Reports violations grouped by rule; a clean run "
        "gates flipping enforcement on."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report instead")
        parser.add_argument("--limit", type=int, default=0, help="Max flags to scan (0 = all)")
        parser.add_argument("--samples", type=int, default=5, help="Sample flag ids to record per rule / unknown key")
        parser.add_argument("--team-id", type=int, default=None, help="Restrict the scan to one team (debugging)")

    def handle(self, *args: Any, **options: Any) -> None:
        limit: int = options["limit"]
        samples: int = options["samples"]
        team_id: int | None = options["team_id"]

        sink = UnknownKeyAggregator(max_samples=samples)
        rule_reports: dict[str, RuleReport] = {}
        scanned = 0
        flags_with_violations = 0

        # _base_manager: the default manager excludes soft-deleted flags, and a restored flag
        # must not resurrect a violation.
        queryset = FeatureFlag._base_manager.all()
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)
        rows = queryset.order_by("id").values_list("id", "team_id", "filters")
        if limit:
            rows = rows[:limit]

        # collect_filters_violations runs CROSS_FIELD_CHECKS, which deliberately excludes
        # check_groups_non_empty_for_create: non-empty groups is a POST-only rule (#50084,
        # haacked, 2026-07-20) — stored flags with empty groups are valid state and must
        # never show up in this report.
        for flag_id, flag_team_id, filters in rows.iterator(chunk_size=500):
            scanned += 1
            violations = collect_filters_violations(filters, context={"unknown_keys_sink": sink, "flag_id": flag_id})
            if not violations:
                continue
            flags_with_violations += 1
            counted_rules: set[str] = set()
            for violation in violations:
                report = rule_reports.setdefault(violation.rule_id, RuleReport(rule_id=violation.rule_id))
                report.total_violations += 1
                if violation.rule_id in counted_rules:
                    continue
                counted_rules.add(violation.rule_id)
                report.flags_affected += 1
                if len(report.sample_flag_ids) < samples:
                    report.sample_flag_ids.append(flag_id)
                    report.sample_details.append(
                        f"flag={flag_id} team={flag_team_id} {violation.path}: {violation.message}"
                    )

        reports = sorted(rule_reports.values(), key=lambda r: (-r.flags_affected, r.rule_id))
        if options["json"]:
            self._emit_json(scanned, flags_with_violations, reports, sink)
        else:
            self._emit_console(scanned, flags_with_violations, reports, sink)

    @staticmethod
    def _is_legacy(level: str, key: str) -> bool:
        return level == "filters" and key in LEGACY_UNKNOWN_FILTER_KEYS

    def _emit_json(
        self, scanned: int, flags_with_violations: int, reports: list[RuleReport], sink: UnknownKeyAggregator
    ) -> None:
        payload = {
            "scanned": scanned,
            "flags_with_violations": flags_with_violations,
            "clean": flags_with_violations == 0,
            "rules": [report.__dict__ for report in reports],
            "unknown_keys": [
                {
                    "level": level,
                    "key": key,
                    "legacy": self._is_legacy(level, key),
                    "flags_affected": count,
                    "sample_flag_ids": sink.sample_flag_ids.get((level, key), []),
                }
                for (level, key), count in sorted(sink.flag_counts.items())
            ],
        }
        self.stdout.write(json.dumps(payload, indent=2))

    def _emit_console(
        self, scanned: int, flags_with_violations: int, reports: list[RuleReport], sink: UnknownKeyAggregator
    ) -> None:
        clean = scanned - flags_with_violations
        self.stdout.write(
            f"Scanned {scanned} flags (soft-deleted included); {clean} clean, {flags_with_violations} with violations."
        )

        if reports:
            self.stdout.write("")
            self.stdout.write("Violations by rule:")
            for report in reports:
                ids = ", ".join(str(flag_id) for flag_id in report.sample_flag_ids)
                self.stdout.write(
                    self.style.ERROR(
                        f"  {report.rule_id} — {report.flags_affected} flags "
                        f"({report.total_violations} violations)  sample ids: {ids}"
                    )
                )
                for detail in report.sample_details:
                    self.stdout.write(f"      {detail}")
        else:
            self.stdout.write(self.style.SUCCESS("No violations found."))

        if sink.flag_counts:
            self.stdout.write("")
            self.stdout.write("Unknown keys dropped by enforcement (frequency):")
            for (level, key), count in sorted(sink.flag_counts.items(), key=lambda item: (-item[1], item[0])):
                legacy_marker = "  [legacy]" if self._is_legacy(level, key) else ""
                ids = ", ".join(str(flag_id) for flag_id in sink.sample_flag_ids.get((level, key), []))
                self.stdout.write(f"  {level:<9} {key:<40} {count} flags  sample ids: {ids}{legacy_marker}")
