"""Recompute the ICP fit score for every org from its latest archived provider payload.

The score-side sibling of backfill_enrichment_fields (which owns the firmographic keys and
never touches any score): this command writes ONLY the icp_fit_* keys — a fit-only
write_organization_enrichment call — so the two backfills stay independently re-runnable,
and the legacy clay icp_score is never touched here.
No new Harmonic calls: everything replays from the fetch archive. A sentinel (miss) archive
row scores as not_found, which is recorded rather than skipped so the re-enrichment sweep
can find those orgs.

Role for the student disqualification comes from the record's signup_role key, persisted at
signup since the fit score shipped; historical orgs without it simply score without the
student DQ.

--parity is the offline validation harness: score payload files from disk against an
expected CSV (the RevOps validation set) with no DB writes, exiting non-zero on any
mismatch. Payloads may be REST-shaped (scored directly; matched-ness = payload has an `id`)
or GraphQL-shaped (normalized through harmonic_adapter first, like production), detected
per payload. Lists come from --tags-csv/--investors-csv when given (no DB dependency),
else from the active IcpScoringConfig row.
"""

import csv
import glob
import gzip
import json
import time
import statistics
from pathlib import Path
from typing import Any, Optional

from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.ph_client import get_regional_ph_client
from posthog.utils import get_instance_region

from products.growth.backend.enrichment import icp_lists as icp_lists_module
from products.growth.backend.enrichment.core import latest_matched_payload
from products.growth.backend.enrichment.fit_score import IcpFitResult, score_company
from products.growth.backend.enrichment.harmonic_adapter import normalize_graphql_company
from products.growth.backend.enrichment.icp_lists import (
    CuratedLists,
    load_active_lists,
    norm,
    parse_investors_csv_rows,
    parse_tags_csv_rows,
)
from products.growth.backend.enrichment.labels import recent_latest_fetches_qs, signup_domain_for_organization
from products.growth.backend.enrichment.writer import write_organization_enrichment
from products.growth.backend.models import OrganizationEnrichment


class _Stats:
    def __init__(self) -> None:
        self.statuses: dict[str, int] = {}
        self.scores: list[int] = []

    def add(self, result: IcpFitResult) -> None:
        self.statuses[result.status] = self.statuses.get(result.status, 0) + 1
        if result.status == "scored" and result.score is not None:
            self.scores.append(result.score)

    def summary(self) -> str:
        total = sum(self.statuses.values())
        lines = [f"evaluated {total}"]
        for status, count in sorted(self.statuses.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {status}: {count} ({count / total:.1%})")
        if self.scores:
            ordered = sorted(self.scores)
            share = lambda threshold: sum(1 for s in ordered if s >= threshold) / len(ordered)  # noqa: E731
            lines.append(
                f"  scored: median {statistics.median(ordered):.0f} | "
                f">=40 {share(40):.1%} | >=50 {share(50):.1%} | >=60 {share(60):.1%} | >=70 {share(70):.1%}"
            )
        return "\n".join(lines)


def _normalize_any_payload(payload: Any) -> Optional[dict[str, Any]]:
    """Accept either archive/GraphQL shape (normalized) or REST shape (passed through)."""
    if not isinstance(payload, dict) or not payload:
        return None
    if "traction_metrics" in payload or "tags_v2" in payload or "id" in payload:
        # REST shape: matched-ness is the `id` key, per the validation reference.
        return payload if payload.get("id") else None
    return normalize_graphql_company(payload)


def _lists_from_csvs(tags_csv: str, investors_csv: str) -> CuratedLists:
    def read(path: str) -> list[dict[str, Any]]:
        with open(path, newline="", encoding="utf-8-sig") as handle:
            return list(csv.DictReader(handle))

    tags = parse_tags_csv_rows(read(tags_csv))
    investors = parse_investors_csv_rows(read(investors_csv))
    buckets: dict[str, set[str]] = {bucket: set() for bucket in icp_lists_module.TAG_BUCKETS}
    for row in tags:
        for bucket in row["recommendation"].split("+"):
            if bucket in buckets:
                buckets[bucket].add(norm(row["tag"]))
    names: set[str] = set()
    for row in investors:
        names.add(norm(row["investor"]))
        names.update(norm(alias) for alias in row["aliases"])
    return CuratedLists(
        version="csv-local",
        capital_quality=frozenset(buckets["capital_quality"]),
        ai_positive=frozenset(buckets["ai_positive"]),
        software_positive=frozenset(buckets["software_positive"]),
        software_negative=frozenset(buckets["software_negative"]),
        dq=frozenset(buckets["dq"]),
        quality_investors=frozenset(names),
    )


def _iter_parity_payloads(path: str):
    """Yield (domain, payload) from a JSONL(.gz) file or a directory of per-domain JSON files."""
    p = Path(path)
    if p.is_dir():
        for fp in sorted(glob.glob(str(p / "*.json"))):
            doc = json.load(open(fp))
            yield (doc.get("_domain") or Path(fp).stem).lower(), doc.get("payload")
        return
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            domain = (doc.get("domain") or doc.get("_domain") or "").lower()
            yield domain, doc.get("company") if "company" in doc else doc.get("payload")


class Command(BaseCommand):
    help = (
        "Recompute ICP fit scores from each organization's latest archived provider fetch "
        "and write the score keys (fit-only; firmographic fields are "
        "backfill_enrichment_fields' job). --parity scores payload files from disk against "
        "an expected CSV instead, with no writes."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--limit", type=int, default=None, help="Backfill at most this many organizations")
        parser.add_argument("--delay", type=float, default=0.05, help="Seconds to sleep between writes")
        parser.add_argument("--dry-run", action="store_true", help="Report what would be written without writing")
        parser.add_argument("--stats", action="store_true", help="Print the score distribution summary at the end")
        parser.add_argument("--parity", action="store_true", help="Offline parity mode: no DB writes")
        parser.add_argument("--payloads", help="Parity: JSONL(.gz) file or directory of payload JSON files")
        parser.add_argument("--expected", help="Parity: CSV of expected score/status per domain")
        parser.add_argument("--tags-csv", help="Score with lists parsed from this tags export instead of the DB row")
        parser.add_argument("--investors-csv", help="Goes with --tags-csv")

    def handle(self, *args: Any, **options: Any) -> None:
        if options["parity"]:
            self._run_parity(options)
            return
        self._run_backfill(options)

    # ---------- backfill ----------

    def _load_lists(self, options: dict[str, Any]) -> CuratedLists:
        if options.get("tags_csv") or options.get("investors_csv"):
            if not (options.get("tags_csv") and options.get("investors_csv")):
                raise CommandError("--tags-csv and --investors-csv must be given together")
            return _lists_from_csvs(options["tags_csv"], options["investors_csv"])
        lists = load_active_lists()
        if lists is None:
            raise CommandError(
                "No active IcpScoringConfig row. Seed one with sync_icp_scoring_lists --activate "
                "(or pass --tags-csv/--investors-csv)."
            )
        return lists

    def _run_backfill(self, options: dict[str, Any]) -> None:
        if get_instance_region() not in ("US", "EU"):
            raise CommandError("Signup enrichment is Cloud-only; refusing to backfill in this region")

        limit: int | None = options["limit"]
        delay: float = options["delay"]
        dry_run: bool = options["dry_run"]
        if limit is not None and limit < 1:
            raise CommandError("--limit must be a positive integer")
        if delay < 0:
            raise CommandError("--delay must be >= 0")

        lists = self._load_lists(options)
        pha_client = get_regional_ph_client()
        if pha_client is None:
            raise CommandError("no PostHog client for this instance's region; refusing to backfill")
        stats = _Stats()

        fetches = recent_latest_fetches_qs().select_related("organization")
        if limit is not None:
            fetches = fetches[:limit]

        try:
            considered = written = skipped_org_gone = 0
            for fetch in fetches.iterator():
                considered += 1
                try:
                    organization = fetch.organization
                except Exception:
                    organization = None
                if organization is None:
                    # db_constraint=False allows orphan archive rows after org deletion; a score
                    # write (and its group projection) for a dead org is pointless.
                    skipped_org_gone += 1
                    continue

                domain = signup_domain_for_organization(organization)
                record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
                role = record.data.get("signup_role") if record else None

                payload = _normalize_any_payload(fetch.payload)
                if payload is None:
                    # Same lookback the live path uses: the latest fetch alone can be a flaky
                    # miss even when an earlier one matched.
                    payload = _normalize_any_payload(latest_matched_payload(str(fetch.organization_id)))
                result = score_company(payload, lists=lists, role=role, domain=domain)
                stats.add(result)

                if dry_run:
                    written += 1
                    self.stdout.write(f"would write {fetch.organization_id}: {result.status} score={result.score}")
                    continue

                write_organization_enrichment(
                    organization_id=str(fetch.organization_id), fields=None, pha_client=pha_client, fit=result
                )
                written += 1
                self.stdout.write(f"wrote {fetch.organization_id}: {result.status} score={result.score}")
                if delay:
                    time.sleep(delay)
        finally:
            pha_client.shutdown()

        verb = "would write" if dry_run else "wrote"
        self.stdout.write(
            self.style.SUCCESS(f"considered {considered}, {verb} {written}, skipped_org_gone {skipped_org_gone}")
        )
        if options["stats"]:
            self.stdout.write(stats.summary())

    # ---------- parity ----------

    _PARITY_COMPONENTS = ("traction", "capital", "ai_pilled", "headcount_growth", "software_relevance")

    def _run_parity(self, options: dict[str, Any]) -> None:
        if not options.get("payloads"):
            raise CommandError("--parity requires --payloads")
        lists = self._load_lists(options)

        expected: dict[str, dict[str, str]] = {}
        if options.get("expected"):
            with open(options["expected"], newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    expected[row["domain"].strip().lower()] = row

        stats = _Stats()
        mismatches = 0
        compared = 0
        for domain, raw_payload in _iter_parity_payloads(options["payloads"]):
            payload = _normalize_any_payload(raw_payload)
            result = score_company(payload, lists=lists, domain=domain)
            stats.add(result)
            want = expected.get(domain)
            if want is None:
                continue
            compared += 1
            diffs = self._parity_diffs(want, result)
            if diffs:
                mismatches += 1
                self.stdout.write(f"MISMATCH {domain}: " + ", ".join(diffs))

        self.stdout.write(stats.summary())
        if expected:
            self.stdout.write(f"compared {compared} against expected; mismatches {mismatches}")
            if mismatches:
                raise CommandError(f"parity failed: {mismatches} mismatches")
            self.stdout.write(self.style.SUCCESS("parity passed"))

    def _parity_diffs(self, want: dict[str, str], result: IcpFitResult) -> list[str]:
        diffs = []
        want_score = want.get("score", "")
        got_score = "" if result.score is None else str(result.score)
        if want_score != got_score:
            diffs.append(f"score want={want_score!r} got={got_score!r}")
        if want.get("status", "") != result.status:
            diffs.append(f"status want={want.get('status')!r} got={result.status!r}")
        components = result.components or {}
        for key in self._PARITY_COMPONENTS:
            want_value = want.get(key, "")
            if want_value == "" and result.status != "scored":
                continue
            got_value = "" if key not in components else str(components[key])
            if want_value != got_value:
                diffs.append(f"{key} want={want_value!r} got={got_value!r}")
        return diffs
