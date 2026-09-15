"""Recompute the ICP fit score for every org from its latest archived provider payload.

The score-side sibling of fields_backfill (which owns the firmographic keys and never touches
any score): this writes ONLY the icp_fit_* keys — a fit-only write_organization_enrichment
call — so the two backfills stay independently re-runnable, and the legacy clay icp_score is
never touched here. No new Harmonic calls: everything replays from the fetch archive. A
sentinel (miss) archive row scores as not_found, which is recorded rather than skipped so the
re-enrichment sweep can find those orgs.

Role for the student disqualification comes from the record's signup_role key, persisted at
signup since the fit score shipped; historical orgs without it simply score without the
student DQ.

Parity is the offline validation harness: score payload files from disk against an expected
CSV (the RevOps validation set) with no DB writes. Payloads may be REST-shaped (scored
directly; matched-ness = payload has an `id`) or GraphQL-shaped (normalized through
harmonic_adapter first, like production), detected per payload. Lists come from the two CSV
exports when given (no DB dependency), else from the active IcpScoringConfig row.
"""

import csv
import glob
import gzip
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Optional

from posthoganalytics.client import Client

from posthog.exceptions_capture import capture_exception
from posthog.models.organization import Organization
from posthog.ph_client import get_regional_ph_client

from products.growth.backend.enrichment import (
    gates,
    icp_lists as icp_lists_module,
)
from products.growth.backend.enrichment.bridge import read_organization_bridge_inputs
from products.growth.backend.enrichment.context import FIT_EVALUATION_KIND_BACKFILL
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
from products.growth.backend.facade.contracts import (
    FitBackfillItem,
    NoActiveScoringLists,
    NoRegionalClient,
    ParityItem,
    ParityRun,
    RegionNotAllowed,
    ScoringListsIncomplete,
)
from products.growth.backend.models import OrganizationEnrichment, OrganizationEnrichmentFetch

_PARITY_COMPONENTS = ("traction", "capital", "ai_pilled", "headcount_growth", "software_relevance")


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


def _load_lists(*, tags_csv: str | None, investors_csv: str | None) -> CuratedLists:
    if tags_csv or investors_csv:
        if not (tags_csv and investors_csv):
            raise ScoringListsIncomplete()
        return _lists_from_csvs(tags_csv, investors_csv)
    lists = load_active_lists()
    if lists is None:
        raise NoActiveScoringLists()
    return lists


def ensure_backfill_allowed() -> None:
    if not gates.region_allowed():
        raise RegionNotAllowed()


def _wizard_ai_sdk_for_backfill(*, organization_id: str, record: Optional[OrganizationEnrichment]) -> Optional[bool]:
    flags = record.data.get("icp_fit_flags") if record else None
    persisted = isinstance(flags, dict) and flags.get("wizard_ai_sdk") is True
    try:
        return read_organization_bridge_inputs(organization_id=organization_id).wizard.ai_sdk_detected
    except Exception as e:
        capture_exception(e, {"organization_id": organization_id})
        return True if persisted else None


def _score_backfill_fetch(
    *, fetch: OrganizationEnrichmentFetch, organization: Organization, lists: CuratedLists
) -> Optional[IcpFitResult]:
    domain = signup_domain_for_organization(organization)
    record = OrganizationEnrichment.objects.filter(organization_id=fetch.organization_id).first()
    role = record.data.get("signup_role") if record else None

    payload = _normalize_any_payload(fetch.payload)
    if payload is None:
        payload = _normalize_any_payload(latest_matched_payload(str(fetch.organization_id)))

    wizard_ai_sdk = _wizard_ai_sdk_for_backfill(organization_id=str(fetch.organization_id), record=record)
    if wizard_ai_sdk is None:
        return None
    return score_company(
        payload,
        lists=lists,
        role=role,
        domain=domain,
        wizard_ai_sdk=wizard_ai_sdk,
    )


def _process_fetch(
    *, fetch: OrganizationEnrichmentFetch, lists: CuratedLists, pha_client: Client, dry_run: bool
) -> FitBackfillItem:
    organization_id = str(fetch.organization_id)
    try:
        organization = fetch.organization
    except Exception:
        organization = None
    if organization is None:
        return FitBackfillItem(organization_id=organization_id, outcome="skipped_org_gone")

    result = _score_backfill_fetch(fetch=fetch, organization=organization, lists=lists)
    if result is None:
        return FitBackfillItem(organization_id=organization_id, outcome="skipped_wizard_unavailable")

    if not dry_run:
        write_organization_enrichment(
            organization_id=organization_id,
            fields=None,
            pha_client=pha_client,
            fit=result,
            fit_evaluation_kind=FIT_EVALUATION_KIND_BACKFILL,
        )
    return FitBackfillItem(organization_id=organization_id, outcome="written", status=result.status, score=result.score)


def backfill_icp_fit_scores(
    *,
    limit: int | None,
    delay: float,
    dry_run: bool,
    tags_csv: str | None,
    investors_csv: str | None,
) -> Iterator[FitBackfillItem]:
    ensure_backfill_allowed()
    lists = _load_lists(tags_csv=tags_csv, investors_csv=investors_csv)
    pha_client = get_regional_ph_client()
    if pha_client is None:
        raise NoRegionalClient()
    return _iter_backfill(lists=lists, pha_client=pha_client, limit=limit, delay=delay, dry_run=dry_run)


def _iter_backfill(
    *, lists: CuratedLists, pha_client: Client, limit: int | None, delay: float, dry_run: bool
) -> Iterator[FitBackfillItem]:
    fetches = recent_latest_fetches_qs().select_related("organization")
    if limit is not None:
        fetches = fetches[:limit]
    try:
        for fetch in fetches.iterator():
            item = _process_fetch(fetch=fetch, lists=lists, pha_client=pha_client, dry_run=dry_run)
            yield item
            if item.outcome == "written" and not dry_run and delay:
                time.sleep(delay)
    finally:
        pha_client.shutdown()


def _iter_parity_payloads(path: str) -> Iterator[tuple[str, Any]]:
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


def _parity_diffs(want: dict[str, str], result: IcpFitResult) -> list[str]:
    diffs = []
    want_score = want.get("score", "")
    got_score = "" if result.score is None else str(result.score)
    if want_score != got_score:
        diffs.append(f"score want={want_score!r} got={got_score!r}")
    if want.get("status", "") != result.status:
        diffs.append(f"status want={want.get('status')!r} got={result.status!r}")
    components = result.components or {}
    for key in _PARITY_COMPONENTS:
        want_value = want.get(key, "")
        if want_value == "" and result.status != "scored":
            continue
        got_value = "" if key not in components else str(components[key])
        if want_value != got_value:
            diffs.append(f"{key} want={want_value!r} got={got_value!r}")
    return diffs


def score_parity(*, payloads: str, expected: str | None, tags_csv: str | None, investors_csv: str | None) -> ParityRun:
    lists = _load_lists(tags_csv=tags_csv, investors_csv=investors_csv)

    expectations: dict[str, dict[str, str]] = {}
    if expected:
        with open(expected, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                expectations[row["domain"].strip().lower()] = row

    return ParityRun(expectations=len(expectations), items=_iter_parity(payloads, lists, expectations))


def _iter_parity(payloads: str, lists: CuratedLists, expectations: dict[str, dict[str, str]]) -> Iterator[ParityItem]:
    for domain, raw_payload in _iter_parity_payloads(payloads):
        payload = _normalize_any_payload(raw_payload)
        result = score_company(payload, lists=lists, domain=domain)
        want = expectations.get(domain)
        diffs = tuple(_parity_diffs(want, result)) if want is not None else None
        yield ParityItem(domain=domain, status=result.status, score=result.score, diffs=diffs)
