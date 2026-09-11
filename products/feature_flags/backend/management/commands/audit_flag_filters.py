"""Read-only audit of `FeatureFlag.filters` against the #50084 structural + cross-field rules.

Reports violations grouped by rule, plus a frequency table of unknown keys that enforcement
would drop. A clean run (zero violations) is the gate for flipping enforcement on; unknown
keys are informational (they get dropped silently by design). Contextual rules (cohort
existence, circular dependencies, size limits, feature gates) are already enforced at write
time in FeatureFlagSerializer and are not audited.

Each flag costs a DRF serializer instantiation, so a full prod scan takes minutes, not
seconds — it's an offline command.

A third section counts the `filters` round-trip divergences between the two flags-cache
builders: shapes the Rust builder writes back narrower than the stored JSONB holds. They are
never violations, because a clean violations run gates flipping enforcement on. Each count is
reported over all stored flags and over the flags the verifier actually compares.
DIVERGENCE_NOTE carries the operator-facing explanation.
"""

import re
import json
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.dataclasses import frozen
from posthog.models import Team

from products.feature_flags.backend.api.filters_schema import (
    FEATURE_FLAG_OPERATOR_ALIASES,
    FLAG_ID_CONTEXT_KEY,
    UNKNOWN_KEYS_SINK_CONTEXT_KEY,
    is_legacy_unknown_key,
)
from products.feature_flags.backend.filters_validation import Violation, collect_filters_violations
from products.feature_flags.backend.flags_cache import _is_unevaluable
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Unknown keys come from user-controlled JSON, so the distinct-key space is unbounded; cap it
# to keep a pathological prod scan from growing the aggregator without limit.
MAX_TRACKED_UNKNOWN_KEYS = 1000

# C0/C1 control characters (incl. tab, newline, ESC, OSC): stored filter junk is
# user-controlled and the console report prints keys and values verbatim, so strip anything
# a terminal could interpret — a newline in a key could forge a fake report line.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitize_for_console(text: str) -> str:
    return _CONTROL_CHARS_RE.sub("�", text)


@frozen
class ScannedFlag:
    id: int
    team_id: int
    filters: Any
    active: bool
    deleted: bool
    has_encrypted_payloads: bool | None


@frozen
class Divergence:
    shape_id: str
    detail: str


def _iter_flag_rows(queryset: Any, *, limit: int, chunk_size: int = 500) -> Iterator[ScannedFlag]:
    # Keyset pagination instead of .iterator(): prod runs behind PgBouncer with server-side
    # cursors disabled, so .iterator() buffers the entire result set client-side on execute
    # and a full scan would hold every flag's filters JSON in memory at once. Repeated
    # id-bounded LIMIT queries keep memory bounded on any connection.
    base = queryset.order_by("id").values_list(
        "id", "team_id", "filters", "active", "deleted", "has_encrypted_payloads"
    )
    last_id, yielded = 0, 0
    while True:
        page = chunk_size if not limit else min(chunk_size, limit - yielded)
        if page <= 0:
            return
        chunk = list(base.filter(id__gt=last_id)[:page])
        if not chunk:
            return
        for row in chunk:
            yield ScannedFlag(
                id=row[0],
                team_id=row[1],
                filters=row[2],
                active=row[3],
                deleted=row[4],
                has_encrypted_payloads=row[5],
            )
        yielded += len(chunk)
        last_id = chunk[-1][0]


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
        self.untracked_keys = 0
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
            if pair not in self.flag_counts and len(self.flag_counts) >= MAX_TRACKED_UNKNOWN_KEYS:
                self.untracked_keys += 1
                continue
            self.flag_counts[pair] = self.flag_counts.get(pair, 0) + 1
            samples = self.sample_flag_ids.setdefault(pair, [])
            if flag_id is not None and len(samples) < self.max_samples:
                samples.append(flag_id)


# MultivariateFlagOptions, MultivariateFlagVariant and Holdout
# (rust/feature-flags/src/flags/flag_models.rs) are the only three Rust structs without
# `#[serde(flatten)] extra`, so Rust drops every other key at these levels on cache write. Every
# other level has `extra` and round-trips unknown keys unchanged. `description` on a variant is
# dropped even though filters_schema.py declares and keeps it. A field added to one of these three
# structs belongs here too, or this audit counts a divergence that no longer happens.
RUST_MULTIVARIATE_FIELDS = frozenset({"variants"})
RUST_VARIANT_FIELDS = frozenset({"key", "name", "rollout_percentage"})
RUST_HOLDOUT_FIELDS = frozenset({"id", "exclusion_percentage"})

DIVERGENCE_NUMERIC_PROPERTY_KEY = "roundtrip.numeric_property_key"
DIVERGENCE_DROPPED_KEY = "roundtrip.dropped_key"
DIVERGENCE_OPERATOR_ALIAS = "roundtrip.operator_alias"
DIVERGENCE_ABSENT_GROUPS = "roundtrip.absent_groups"

# Fixed set, so a shape that matches nothing still reports its zero.
DIVERGENCE_SHAPES: tuple[str, ...] = (
    DIVERGENCE_NUMERIC_PROPERTY_KEY,
    DIVERGENCE_DROPPED_KEY,
    DIVERGENCE_OPERATOR_ALIAS,
    DIVERGENCE_ABSENT_GROUPS,
)

DIVERGENCE_NOTE = """\
These are cache-write divergences, not enforcement violations, so they do not affect the
clean-run gate above. The two builders differ in the bytes they write, not in what the flag
resolves to for a user. The Python cache verifier reports the difference as a filters mismatch
and repairs it on every pass.
The second number counts only the flags whose stored filters the verifier compares. It leaves
out a flag that is inactive or deleted, a flag with encrypted payloads, and a flag with a
structural violation, because no cache entry holds the stored filters of any of those. Each
sampled detail says which one applies.
Size a verifier fix from the second number, and a stored-data rewrite from the first.\
"""


def _iter_divergences(filters: Any) -> Iterator[Divergence]:
    """Yield one Divergence per round-trip divergence in one stored filters blob."""
    # Every level is type-guarded because a blob Rust cannot deserialize at all is reported by
    # collect_filters_violations, not counted here.
    if not isinstance(filters, dict):
        return
    if "groups" not in filters:
        yield Divergence(shape_id=DIVERGENCE_ABSENT_GROUPS, detail='no groups key, and Rust writes "groups": []')
    # Only `groups` is typed on the Rust side. super_groups and holdout_groups reach the `extra`
    # map as raw JSON, so their contents come back byte-identical.
    groups = filters.get("groups")
    if isinstance(groups, list):
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            properties = group.get("properties")
            if not isinstance(properties, list):
                continue
            for property_index, property_filter in enumerate(properties):
                if not isinstance(property_filter, dict):
                    continue
                yield from _iter_property_divergences(
                    property_filter, f"groups[{group_index}].properties[{property_index}]"
                )
    multivariate = filters.get("multivariate")
    if isinstance(multivariate, dict):
        yield from _iter_dropped_keys(multivariate, RUST_MULTIVARIATE_FIELDS, "multivariate")
        variants = multivariate.get("variants")
        if isinstance(variants, list):
            for variant_index, variant in enumerate(variants):
                if isinstance(variant, dict):
                    yield from _iter_dropped_keys(
                        variant, RUST_VARIANT_FIELDS, f"multivariate.variants[{variant_index}]"
                    )
    holdout = filters.get("holdout")
    if isinstance(holdout, dict):
        yield from _iter_dropped_keys(holdout, RUST_HOLDOUT_FIELDS, "holdout")


def _iter_property_divergences(property_filter: dict[str, Any], path: str) -> Iterator[Divergence]:
    key = property_filter.get("key")
    # isinstance(True, int) is True in Python, and Rust's `deserialize_key` takes a string or a
    # JSON number only, so a bool key fails deserialization instead of round-tripping narrowed.
    if not isinstance(key, bool) and isinstance(key, int | float):
        yield Divergence(
            shape_id=DIVERGENCE_NUMERIC_PROPERTY_KEY, detail=f"{path}.key: the number {key} becomes a string"
        )
    operator = property_filter.get("operator")
    if isinstance(operator, str) and operator in FEATURE_FLAG_OPERATOR_ALIASES:
        canonical = FEATURE_FLAG_OPERATOR_ALIASES[operator]
        yield Divergence(shape_id=DIVERGENCE_OPERATOR_ALIAS, detail=f"{path}.operator: {operator} becomes {canonical}")


def _iter_dropped_keys(level: dict[str, Any], kept_by_rust: frozenset[str], path: str) -> Iterator[Divergence]:
    # The verifier's _strip_null_values drops a null-valued key from the stored side too, so both
    # sides come out equal even though Rust never wrote the key.
    for key, value in level.items():
        if key not in kept_by_rust and value is not None:
            yield Divergence(shape_id=DIVERGENCE_DROPPED_KEY, detail=f"{path}.{key} is dropped")


@frozen(frozen=False)
class DivergenceReport:
    shape_id: str
    flags_affected: int = 0
    # Only these can make the verifier report a mismatch. See _not_compared_reason.
    compared_flags_affected: int = 0
    sample_flag_ids: list[int] = field(default_factory=list)
    sample_details: list[str] = field(default_factory=list)


def _not_compared_reason(flag: ScannedFlag, *, structurally_valid: bool) -> str | None:
    """Why the verifier never compares this flag's stored filters, or None when it does."""
    # _is_unevaluable is the cache builders' own gate, so a change to what they blank cannot
    # leave this count quietly wrong.
    if _is_unevaluable({"active": flag.active, "deleted": flag.deleted}):
        return "inactive or deleted"
    # An encrypted-payload flag is served from /remote_config, and _get_feature_flags_for_teams_batch
    # excludes it from the payload the verifier compares.
    if flag.has_encrypted_payloads:
        return "encrypted payloads"
    # filters_schema.py mirrors the Rust field shapes, so a blob it rejects structurally is one
    # Rust may fail to deserialize. Rust then writes no narrowed form to diverge from.
    if not structurally_valid:
        return "structural violation"
    return None


class RoundTripDivergenceAggregator:
    """Counts flags per divergence shape, once per shape however often it recurs."""

    def __init__(self, max_samples: int) -> None:
        self.max_samples = max_samples
        self.reports: dict[str, DivergenceReport] = {
            shape_id: DivergenceReport(shape_id=shape_id) for shape_id in DIVERGENCE_SHAPES
        }
        self.flags_with_any_divergence = 0
        self.compared_flags_with_any_divergence = 0

    def record(self, *, flag: ScannedFlag, not_compared: str | None, found: Iterable[Divergence]) -> None:
        counted: set[str] = set()
        for divergence in found:
            if divergence.shape_id in counted:
                continue
            counted.add(divergence.shape_id)
            report = self.reports[divergence.shape_id]
            report.flags_affected += 1
            if not_compared is None:
                report.compared_flags_affected += 1
            if len(report.sample_flag_ids) < self.max_samples:
                report.sample_flag_ids.append(flag.id)
                # Naming the reason saves tracing a sample id back to find out why the verifier
                # never reports it.
                marker = "" if not_compared is None else f" [not compared: {not_compared}]"
                report.sample_details.append(f"flag={flag.id} team={flag.team_id} {divergence.detail}{marker}")
        if counted:
            self.flags_with_any_divergence += 1
            if not_compared is None:
                self.compared_flags_with_any_divergence += 1


class Command(BaseCommand):
    help = (
        "Read-only audit of FeatureFlag.filters (all flags, soft-deleted included) against the "
        "#50084 structural + cross-field rules. Reports violations grouped by rule; a clean run "
        "gates flipping enforcement on. Also counts the filters round-trip divergences between "
        "the Python and Rust cache builders, which are cache-write divergences rather than "
        "enforcement violations and do not affect that gate. The report explains both counts."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--json", action="store_true", help="Emit a machine-readable JSON report instead")
        parser.add_argument("--limit", type=int, default=0, help="Max flags to scan (0 = all)")
        parser.add_argument(
            "--samples",
            type=int,
            default=5,
            help="Sample flag ids to record per rule / unknown key / divergence shape",
        )
        parser.add_argument("--team-id", type=int, default=None, help="Restrict the scan to one team (debugging)")

    def handle(self, *args: Any, **options: Any) -> None:
        limit: int = options["limit"]
        samples: int = options["samples"]
        team_id: int | None = options["team_id"]

        # A negative limit would silently slice away the newest flags (rows[:-N]) and a
        # negative samples cap would drop every diagnostic — both would make a bad scan look
        # authoritative, so fail loudly instead.
        if limit < 0:
            raise CommandError("--limit must be >= 0 (0 scans all flags)")
        if samples < 0:
            raise CommandError("--samples must be >= 0")
        # A mistyped --team-id would scan zero rows and report a false "clean".
        if team_id is not None and not Team.objects.filter(id=team_id).exists():
            raise CommandError(f"Team {team_id} does not exist")

        sink = UnknownKeyAggregator(max_samples=samples)
        divergences = RoundTripDivergenceAggregator(max_samples=samples)
        rule_reports: dict[str, RuleReport] = {}
        scanned = 0
        flags_with_violations = 0

        # objects_including_soft_deleted: the default manager excludes soft-deleted flags, and
        # a restored flag must not resurrect a violation. It is also a RootTeamManager, so
        # --team-id with an environment's team id maps to the project root team instead of
        # silently scanning zero flags.
        queryset = FeatureFlag.objects_including_soft_deleted.all()
        if team_id is not None:
            queryset = queryset.filter(team_id=team_id)

        # collect_filters_violations runs CROSS_FIELD_CHECKS, which deliberately excludes
        # check_groups_non_empty_for_create: non-empty groups is a POST-only rule (#50084) —
        # stored flags with empty groups are valid state and must never show up in this report.
        for flag in _iter_flag_rows(queryset, limit=limit):
            scanned += 1
            try:
                violations = collect_filters_violations(
                    flag.filters, context={UNKNOWN_KEYS_SINK_CONTEXT_KEY: sink, FLAG_ID_CONTEXT_KEY: flag.id}
                )
            except Exception as exc:
                # The whole point of this command is surviving wild-west data: one flag whose
                # junk crashes a validator must become a reported violation, not a dead scan.
                violations = [
                    Violation(
                        rule_id="structural.filters.internal_error",
                        path="filters",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                ]
            divergences.record(
                flag=flag,
                not_compared=_not_compared_reason(
                    flag,
                    structurally_valid=not any(v.rule_id.startswith("structural.") for v in violations),
                ),
                found=_iter_divergences(flag.filters),
            )
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
                    report.sample_flag_ids.append(flag.id)
                    report.sample_details.append(
                        f"flag={flag.id} team={flag.team_id} {violation.path}: {violation.message}"
                    )

        reports = sorted(rule_reports.values(), key=lambda r: (-r.flags_affected, r.rule_id))
        if options["json"]:
            self._emit_json(scanned, flags_with_violations, reports, sink, divergences)
        else:
            self._emit_console(scanned, flags_with_violations, reports, sink, divergences)

    def _emit_json(
        self,
        scanned: int,
        flags_with_violations: int,
        reports: list[RuleReport],
        sink: UnknownKeyAggregator,
        divergences: RoundTripDivergenceAggregator,
    ) -> None:
        payload = {
            "scanned": scanned,
            "flags_with_violations": flags_with_violations,
            "clean": flags_with_violations == 0,
            # Enumerate fields explicitly: report.__dict__ would leak any future internal
            # attribute into the machine-readable contract.
            "rules": [
                {
                    "rule_id": report.rule_id,
                    "flags_affected": report.flags_affected,
                    "total_violations": report.total_violations,
                    "sample_flag_ids": report.sample_flag_ids,
                    "sample_details": report.sample_details,
                }
                for report in reports
            ],
            "unknown_keys": [
                {
                    "level": level,
                    "key": key,
                    "legacy": is_legacy_unknown_key(level, key),
                    "flags_affected": count,
                    "sample_flag_ids": sink.sample_flag_ids.get((level, key), []),
                }
                for (level, key), count in sorted(sink.flag_counts.items())
            ],
            "untracked_unknown_keys": sink.untracked_keys,
            "flags_with_roundtrip_divergences": divergences.flags_with_any_divergence,
            "compared_flags_with_roundtrip_divergences": divergences.compared_flags_with_any_divergence,
            "roundtrip_divergences": [
                {
                    "shape_id": report.shape_id,
                    "flags_affected": report.flags_affected,
                    "compared_flags_affected": report.compared_flags_affected,
                    "sample_flag_ids": report.sample_flag_ids,
                    "sample_details": report.sample_details,
                }
                for report in divergences.reports.values()
            ],
            "roundtrip_divergences_note": DIVERGENCE_NOTE,
        }
        self.stdout.write(json.dumps(payload, indent=2))

    def _emit_console(
        self,
        scanned: int,
        flags_with_violations: int,
        reports: list[RuleReport],
        sink: UnknownKeyAggregator,
        divergences: RoundTripDivergenceAggregator,
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
                    self.stdout.write(f"      {_sanitize_for_console(detail)}")
        else:
            self.stdout.write(self.style.SUCCESS("No violations found."))

        if sink.flag_counts:
            self.stdout.write("")
            self.stdout.write("Unknown keys dropped by enforcement (frequency):")
            for (level, key), count in sorted(sink.flag_counts.items(), key=lambda item: (-item[1], item[0])):
                legacy_marker = "  [legacy]" if is_legacy_unknown_key(level, key) else ""
                ids = ", ".join(str(flag_id) for flag_id in sink.sample_flag_ids.get((level, key), []))
                self.stdout.write(
                    f"  {level:<9} {_sanitize_for_console(key):<40} {count} flags  sample ids: {ids}{legacy_marker}"
                )
            if sink.untracked_keys:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ... plus {sink.untracked_keys} occurrence(s) of keys beyond the "
                        f"{MAX_TRACKED_UNKNOWN_KEYS} distinct-key tracking cap"
                    )
                )

        self._emit_divergences_console(divergences)

    def _emit_divergences_console(self, divergences: RoundTripDivergenceAggregator) -> None:
        self.stdout.write("")
        self.stdout.write(
            f"Cache-write round-trip divergences ({divergences.flags_with_any_divergence} flags, "
            f"{divergences.compared_flags_with_any_divergence} compared by the verifier):"
        )
        for report in sorted(divergences.reports.values(), key=lambda r: (-r.flags_affected, r.shape_id)):
            ids = ", ".join(str(flag_id) for flag_id in report.sample_flag_ids)
            self.stdout.write(
                f"  {report.shape_id:<30} {report.flags_affected} flags, "
                f"{report.compared_flags_affected} compared  sample ids: {ids}"
            )
            for detail in report.sample_details:
                self.stdout.write(f"      {_sanitize_for_console(detail)}")
        if divergences.flags_with_any_divergence:
            for line in DIVERGENCE_NOTE.splitlines():
                self.stdout.write(f"  {line}")
