"""Read-only A/B probe of Harmonic lookup strategies for domains the pipeline failed to match.

The validation A2 finding: 55/55 orgs the signup pipeline had left unmatched matched on
fresh manual pulls. Candidate explanations differ in fix and cost — the GraphQL
`websiteUrl` identifier being stricter than REST's `website_domain` matching, the
strict-lookup error conflation (fixed alongside this command), or Harmonic seeding latency
outpacing the single +4h recheck. This probe measures the identifier explanations
directly: for each domain it runs three independent lookups and reports per-variant
outcomes, so the fix (switch identifier / add REST / rely on the sweep) is chosen on
measured hit rates instead of a guess.

Makes no local writes: nothing is archived and no record is touched here. But the
rest_domain variant sends enrich_missing_company=true, which seeds Harmonic-side
enrichment for every probed domain — so results are one-shot, and a repeat run measures
a population the first run already contaminated. Needs HARMONIC_API_KEY, so run it from
a worker shell (the key deliberately never reaches web pods).

Variants per domain:
  graphql_url     — production today: enrichCompanyByIdentifiers {websiteUrl: https://<d>},
                    bare and www. variations, first found wins
  graphql_domain  — {websiteDomain: <d>}; a schema rejection is reported as its own outcome
                    (the identifier may not exist — that is itself an answer)
  rest_domain     — POST /companies?website_domain=<d>&enrich_missing_company=true (what the
                    validation pulls used; also seeds Harmonic's async enrichment)
"""

import csv
import json
import asyncio
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

import aiohttp

from products.growth.backend.enrichment.labels import signup_domain_for_organization
from products.growth.backend.models import OrganizationEnrichmentFetch

from ee.billing.salesforce_enrichment.constants import HARMONIC_BASE_URL, HARMONIC_COMPANY_ENRICHMENT_QUERY

FOUND = "found"
NOT_FOUND = "not_found"
IDENTIFIER_REJECTED = "identifier_rejected"

# Harmonic rate limit is 5 req/s; three variants per domain stay well under it with this.
_SLEEP_BETWEEN_CALLS_SECONDS = 0.25
_REQUEST_TIMEOUT_SECONDS = 30

VARIANTS = ("graphql_url", "graphql_domain", "rest_domain")


def _clean(domain: str) -> str:
    return domain.lower().strip().removeprefix("https://").removeprefix("http://").removeprefix("www.")


async def _graphql_probe(session: aiohttp.ClientSession, api_key: str, identifiers: dict[str, str]) -> str:
    async with session.post(
        f"{HARMONIC_BASE_URL}/graphql",
        json={"query": HARMONIC_COMPANY_ENRICHMENT_QUERY, "variables": {"identifiers": identifiers}},
        headers={"Content-Type": "application/json", "apikey": api_key},
    ) as response:
        if response.status >= 400:
            return f"error:http_{response.status}"
        data = await response.json()
        if "errors" in data:
            message = json.dumps(data["errors"])[:200]
            # A schema-level rejection of the identifier is a distinct, useful outcome.
            if "websiteDomain" in message or "Unknown argument" in message or "not defined" in message:
                return IDENTIFIER_REJECTED
            return f"error:graphql:{message}"
        result = (data.get("data") or {}).get("enrichCompanyByIdentifiers") or {}
        return FOUND if result.get("companyFound") else NOT_FOUND


async def _graphql_url_probe(session: aiohttp.ClientSession, api_key: str, domain: str) -> str:
    # Mirrors production: bare domain first, then www.; first found wins, clean not-found
    # from either counts as not_found.
    outcomes = []
    for variation in (domain, f"www.{domain}"):
        outcome = await _graphql_probe(session, api_key, {"websiteUrl": f"https://{variation}"})
        if outcome == FOUND:
            return FOUND
        outcomes.append(outcome)
        await asyncio.sleep(_SLEEP_BETWEEN_CALLS_SECONDS)
    return NOT_FOUND if NOT_FOUND in outcomes else outcomes[-1]


async def _rest_probe(session: aiohttp.ClientSession, api_key: str, domain: str) -> str:
    async with session.post(
        f"{HARMONIC_BASE_URL}/companies",
        params={"website_domain": domain, "enrich_missing_company": "true"},
        headers={"apikey": api_key},
    ) as response:
        if response.status == 404:
            return NOT_FOUND
        if response.status >= 400:
            return f"error:http_{response.status}"
        data = await response.json()
        return FOUND if isinstance(data, dict) and data.get("id") else NOT_FOUND


async def _probe_domains(domains: list[str], api_key: str, stdout_write) -> list[dict[str, str]]:
    rows = []
    timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
    async with aiohttp.ClientSession(trust_env=True, timeout=timeout) as session:
        for index, domain in enumerate(domains, start=1):
            row: dict[str, str] = {"domain": domain}
            for variant in VARIANTS:
                try:
                    if variant == "graphql_url":
                        row[variant] = await _graphql_url_probe(session, api_key, domain)
                    elif variant == "graphql_domain":
                        row[variant] = await _graphql_probe(session, api_key, {"websiteDomain": domain})
                    else:
                        row[variant] = await _rest_probe(session, api_key, domain)
                except Exception as e:  # network-level; keep probing the rest
                    row[variant] = f"error:{type(e).__name__}"
                await asyncio.sleep(_SLEEP_BETWEEN_CALLS_SECONDS)
            rows.append(row)
            stdout_write(f"[{index}/{len(domains)}] {domain}: " + ", ".join(f"{v}={row[v]}" for v in VARIANTS))
    return rows


def _domains_from_miss_archive(limit: int) -> list[str]:
    """Domains of orgs whose latest archived fetch is the miss sentinel — the population the
    pipeline failed to match, resolved to domains the same way the label runner does."""
    latest = OrganizationEnrichmentFetch.objects.order_by("organization_id", "-fetched_at", "-id").distinct(
        "organization_id"
    )
    domains: list[str] = []
    for fetch in latest.select_related("organization").iterator():
        payload = fetch.payload
        if not (isinstance(payload, dict) and payload.get("companyFound") is False):
            continue
        try:
            domain = signup_domain_for_organization(fetch.organization)
        except Exception:
            continue
        if domain:
            domains.append(domain)
        if len(domains) >= limit:
            break
    return domains


class Command(BaseCommand):
    help = (
        "Read-only A/B probe of Harmonic lookup strategies (GraphQL websiteUrl vs websiteDomain "
        "vs REST website_domain) for domains the pipeline failed to match. Writes nothing to "
        "the archive or the enrichment record."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--domains-file", help="File with one domain per line")
        parser.add_argument(
            "--from-miss-archive",
            action="store_true",
            help="Probe orgs whose latest archived fetch is the miss sentinel",
        )
        parser.add_argument("--limit", type=int, default=50, help="Max domains to probe")
        parser.add_argument("--out", help="Write per-domain outcomes to this CSV")

    def handle(self, *args: Any, **options: Any) -> None:
        api_key = getattr(settings, "HARMONIC_API_KEY", None)
        if not api_key:
            raise CommandError("HARMONIC_API_KEY is not set — run this from a worker shell")
        if bool(options.get("domains_file")) == bool(options.get("from_miss_archive")):
            raise CommandError("Pass exactly one of --domains-file or --from-miss-archive")
        limit: int = options["limit"]
        if limit < 1:
            raise CommandError("--limit must be a positive integer")

        if options.get("domains_file"):
            with open(options["domains_file"], encoding="utf-8") as handle:
                domains = [_clean(line) for line in handle if line.strip()][:limit]
        else:
            domains = _domains_from_miss_archive(limit)
        if not domains:
            raise CommandError("No domains to probe")

        rows = asyncio.run(_probe_domains(domains, api_key, self.stdout.write))

        if options.get("out"):
            with open(options["out"], "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=["domain", *VARIANTS])
                writer.writeheader()
                writer.writerows(rows)
            self.stdout.write(f"wrote {options['out']}")

        total = len(rows)
        self.stdout.write(self.style.SUCCESS(f"probed {total} domains"))
        for variant in VARIANTS:
            found = sum(1 for row in rows if row[variant] == FOUND)
            errors = sum(1 for row in rows if row[variant].startswith("error:"))
            rejected = sum(1 for row in rows if row[variant] == IDENTIFIER_REJECTED)
            extra = f", identifier_rejected {rejected}" if rejected else ""
            self.stdout.write(f"  {variant}: found {found}/{total} ({found / total:.0%}), errors {errors}{extra}")
        rest_only = sum(1 for row in rows if row["rest_domain"] == FOUND and row["graphql_url"] != FOUND)
        domain_only = sum(1 for row in rows if row["graphql_domain"] == FOUND and row["graphql_url"] != FOUND)
        self.stdout.write(f"  found by REST but not by production graphql_url: {rest_only}")
        self.stdout.write(f"  found by graphql websiteDomain but not by production graphql_url: {domain_only}")
