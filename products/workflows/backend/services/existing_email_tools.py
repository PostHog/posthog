from concurrent.futures import ThreadPoolExecutor

from django.core.cache import cache

import dns.resolver
import dns.exception
from dns.rdtypes.ANY.CNAME import CNAME
from dns.rdtypes.ANY.TXT import TXT

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


def detect_existing_email_tools(*, spf_records: list[str], dkim_targets: list[str], has_resend_dkim: bool) -> list[str]:
    targets = [*_spf_include_targets(spf_records), *(target.lower() for target in dkim_targets)]
    tools = [tool for marker, tool in _TOOLS_BY_TARGET_MARKER if any(marker in target for target in targets)]
    if has_resend_dkim:
        tools.append("Resend")
    return list(dict.fromkeys(tools))


def lookup_existing_email_tools(root_domain: str) -> list[str]:
    cache_key = f"existing_email_tools:{root_domain}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

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
        has_resend_dkim=bool(answers[_RESEND_DKIM_SELECTOR]),
    )
    # A lookup without an answer says nothing about the domain, so the next check asks again.
    if all(answer is not None for answer in answers.values()):
        cache.set(cache_key, tools, CACHE_SECONDS)
    return tools


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
