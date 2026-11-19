import logging
from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

import dns.resolver
import dns.exception
from dns.rdtypes.ANY.CNAME import CNAME
from dns.rdtypes.ANY.TXT import TXT

from posthog.cloud_utils import is_cloud
from posthog.dataclasses import frozen
from posthog.security.oob_domains import matched_oob_domain

logger = logging.getLogger(__name__)

LOOKUP_TIMEOUT_SECONDS = 3
CACHE_SECONDS = 60 * 60

# Matched as substrings of SPF include targets and DKIM CNAME targets. Customer.io sends through
# Mailgun, so its domains often show up as Mailgun here.
_TOOLS_BY_TARGET_MARKER: tuple[tuple[str, str], ...] = (
    ("customeriomail.com", "Customer.io"),
    ("mcsv.net", "Mailchimp"),
    ("mandrillapp.com", "Mailchimp"),
    ("sendgrid.net", "SendGrid"),
    ("mailgun.org", "Mailgun"),
    ("mtasv.net", "Postmark"),
    ("hubspotemail.net", "HubSpot"),
    ("klaviyo", "Klaviyo"),
    ("brevo.com", "Brevo"),
    ("sendinblue.com", "Brevo"),
)
_DKIM_CNAME_SELECTORS = ("k1", "s1", "kl", "brevo1")
_RESEND_DKIM_SELECTOR = "resend"


def detect_existing_email_tools(
    *, spf_records: list[str], dkim_targets: list[str], resend_dkim_records: list[str]
) -> list[str]:
    targets = [*_spf_include_targets(spf_records), *(target.lower() for target in dkim_targets)]
    tools = [tool for marker, tool in _TOOLS_BY_TARGET_MARKER if any(marker in target for target in targets)]
    if any(_has_dkim_key(record) for record in resend_dkim_records):
        tools.append("Resend")
    return list(dict.fromkeys(tools))


# An empty p= tag carries no key. It revokes a key, and domains that send no mail publish one for every
# selector under a wildcard *._domainkey name, so its presence alone does not mean Resend signs for the domain.
def _has_dkim_key(record: str) -> bool:
    for tag in record.split(";"):
        name, _, value = tag.partition("=")
        if name.strip() == "p":
            return bool(value.strip())
    return False


@frozen
class _ToolLookup:
    tools: list[str]
    every_lookup_answered: bool


def lookup_existing_email_tools(root_domain: str) -> list[str]:
    return _lookup(root_domain).tools


# A lookup without an answer cannot tell "no tool" from "unknown", so this answers None for it.
def lookup_existing_email_tools_when_answered(root_domain: str) -> list[str] | None:
    lookup = _lookup(root_domain)
    return lookup.tools if lookup.every_lookup_answered else None


def _lookup(root_domain: str) -> _ToolLookup:
    # Versioned so that a change to the detection rules is not answered from an entry the old rules cached.
    cache_key = f"existing_email_tools:v2:{root_domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _ToolLookup(tools=cached, every_lookup_answered=True)

    if is_cloud() and (oob_domain := matched_oob_domain(root_domain)) is not None:
        logger.info("security.oob_domain_seen domain=%s guard=existing_email_tools", oob_domain)
        # The lookup alone confirms the path to whoever runs the collaborator, so the name is
        # refused rather than resolved. No tool is reported for it.
        return _ToolLookup(tools=[], every_lookup_answered=False)
    resolver = dns.resolver.Resolver()
    resolver.lifetime = LOOKUP_TIMEOUT_SECONDS
    lookups = {
        "spf": (root_domain, "TXT"),
        _RESEND_DKIM_SELECTOR: (f"{_RESEND_DKIM_SELECTOR}._domainkey.{root_domain}", "TXT"),
        **{selector: (f"{selector}._domainkey.{root_domain}", "CNAME") for selector in _DKIM_CNAME_SELECTORS},
    }
    with ThreadPoolExecutor(max_workers=len(lookups)) as pool:
        answers = dict(zip(lookups, pool.map(lambda lookup: _resolve(resolver, *lookup), lookups.values())))
    tools = detect_existing_email_tools(
        spf_records=_txt_values(answers["spf"]),
        dkim_targets=[target for selector in _DKIM_CNAME_SELECTORS for target in _cname_targets(answers[selector])],
        resend_dkim_records=_txt_values(answers[_RESEND_DKIM_SELECTOR]),
    )
    every_lookup_answered = all(answer is not None for answer in answers.values())
    # A lookup without an answer says nothing about the domain, so the next check asks again.
    if every_lookup_answered:
        cache.set(cache_key, tools, CACHE_SECONDS)
    return _ToolLookup(tools=tools, every_lookup_answered=every_lookup_answered)


def _spf_include_targets(txt_records: list[str]) -> list[str]:
    return [
        term.removeprefix("include:")
        for record in txt_records
        if record.lower().startswith("v=spf1")
        for term in record.lower().split()
        if term.startswith("include:")
    ]


def _txt_values(answers: list[object] | None) -> list[str]:
    return [
        b"".join(rdata.strings).decode("utf-8", errors="replace") for rdata in answers or [] if isinstance(rdata, TXT)
    ]


def _cname_targets(answers: list[object] | None) -> list[str]:
    return [rdata.target.to_text() for rdata in answers or [] if isinstance(rdata, CNAME)]


def _resolve(resolver: dns.resolver.Resolver, name: str, record_type: str) -> list[object] | None:
    try:
        return list(resolver.resolve(name, record_type))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        return []
    except dns.exception.DNSException:
        return None
