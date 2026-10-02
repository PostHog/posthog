import re
import json
import base64
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from django.conf import settings

import requests
import responses
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from products.workflows.backend.test.fakes.fake_dns import FakeDnsZone
from products.workflows.backend.test.fakes.faults import FaultInjector, HttpFault

TEMPLATE_DIR = (
    Path(__file__).resolve().parents[5] / "frontend" / "src" / "lib" / "components" / "DomainConnect" / "templates"
)
CLOUDFLARE_ENDPOINT = "api.cloudflare.com/client/v4/dns/domainconnect"
CLOUDFLARE_SYNC_UX = "https://dash.cloudflare.com/domainconnect"
SETTINGS_OPERATION = "http.get:settings"
_TEMPLATE_VARIABLE = re.compile(r"%(\w+)%")
_SETTINGS_PATH = re.compile(r"/v2/(?P<domain>[^/]+)/settings$")
_APPLY_PATH = re.compile(r"/v2/domainTemplates/providers/(?P<provider>[^/]+)/services/(?P<service>[^/]+)/apply$")


class DomainConnectRejected(Exception):
    pass


class FakeDomainConnectProvider:
    """A Domain Connect DNS provider. Discovery reads the `_domainconnect` TXT record from `FakeDnsZone`, settings
    are served over HTTP, and `apply` checks the signature, renders our real template and publishes its records."""

    def __init__(
        self,
        dns: FakeDnsZone,
        faults: FaultInjector,
        *,
        endpoint: str = CLOUDFLARE_ENDPOINT,
        url_sync_ux: str = CLOUDFLARE_SYNC_UX,
    ) -> None:
        self._dns = dns
        self._faults = faults
        self.endpoint = endpoint
        self.url_sync_ux = url_sync_ux
        self.hosted_domains: set[str] = set()

    @contextmanager
    def installed(self) -> Iterator["FakeDomainConnectProvider"]:
        with responses.RequestsMock(assert_all_requests_are_fired=False) as http:
            http.add_callback(
                responses.GET, re.compile(rf"https://{re.escape(self.endpoint)}/v2/[^/]+/settings"), self._settings
            )
            yield self

    def host(self, root_domain: str) -> None:
        self.hosted_domains.add(root_domain)
        self._dns.publish_txt(f"_domainconnect.{root_domain}", self.endpoint)

    def apply(self, url: str) -> str | None:
        """Approves the apply URL the way a person does at the provider, and returns where it redirects."""
        parts = urlsplit(url)
        if not url.startswith(self.url_sync_ux):
            raise DomainConnectRejected(f"{url} is not this provider's sync URL")
        self._check_signature(parts.query)
        path = _APPLY_PATH.search(parts.path)
        if path is None:
            raise DomainConnectRejected(f"Unknown apply path {parts.path}")
        params = {key: values[0] for key, values in parse_qs(parts.query).items()}
        if params["domain"] not in self.hosted_domains:
            raise DomainConnectRejected(f"{params['domain']} is not hosted here")
        template = _load_template(path["provider"], path["service"])
        redirect_uri = params.get("redirect_uri")
        if redirect_uri and urlsplit(redirect_uri).hostname != template["syncRedirectDomain"]:
            raise DomainConnectRejected(f"{redirect_uri} is outside the template's redirect domain")
        selected_groups = set(params["groupId"].split(",")) if "groupId" in params else None
        for record in template["records"]:
            if selected_groups is None or record.get("groupId") in selected_groups:
                self._publish(_render(record, params), domain=params["domain"], host=params.get("host", ""))
        return redirect_uri

    def _settings(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        settings_path = _SETTINGS_PATH.search(urlsplit(request.url or "").path)
        domain = settings_path["domain"] if settings_path else ""
        match self._faults.fault_for(SETTINGS_OPERATION):
            case HttpFault.TIMEOUT:
                raise requests.exceptions.ConnectTimeout(f"Injected timeout for {request.url}")
            case HttpFault.SERVER_ERROR:
                return 500, {}, "Internal Server Error"
            case HttpFault.RATE_LIMITED:
                return 429, {"Retry-After": "30"}, "Too Many Requests"
            case HttpFault.MALFORMED_JSON:
                return 200, {"Content-Type": "application/json"}, "{not json"
            case HttpFault.MISSING_URL_SYNC_UX:
                return 200, {"Content-Type": "application/json"}, json.dumps({"providerName": "Cloudflare"})
        if domain not in self.hosted_domains:
            return 404, {}, ""
        body = {"providerId": "cloudflare.com", "providerName": "Cloudflare", "urlSyncUX": self.url_sync_ux}
        return 200, {"Content-Type": "application/json"}, json.dumps(body)

    def _check_signature(self, query: str) -> None:
        signed_query, separator, signature_query = query.partition("&sig=")
        if not separator:
            raise DomainConnectRejected("The apply URL is not signed")
        signature = parse_qs(f"sig={signature_query}")
        if signature["key"][0] != settings.DOMAIN_CONNECT_KEY_ID:
            raise DomainConnectRejected(f"Unknown signing key {signature['key'][0]}")
        try:
            _public_key().verify(
                base64.b64decode(signature["sig"][0]), signed_query.encode(), padding.PKCS1v15(), hashes.SHA256()
            )
        except InvalidSignature as error:
            raise DomainConnectRejected("The apply URL signature does not match") from error

    def _publish(self, record: dict[str, Any], *, domain: str, host: str) -> None:
        name = _record_name(record["host"], domain=domain, host=host)
        match record["type"]:
            case "TXT":
                self._dns.publish_txt(name, record["data"])
            case "CNAME":
                self._dns.unpublish(name, "CNAME")
                self._dns.publish(name, "CNAME", f"{record['pointsTo']}.")
            case "MX":
                self._dns.publish(name, "MX", f"{record['priority']} {record['pointsTo']}.")
            case "SPFM":
                self._merge_spf_rules(name, record["spfRules"])
            case unknown:
                raise DomainConnectRejected(f"Unsupported record type {unknown}")

    def _merge_spf_rules(self, name: str, rules: str) -> None:
        existing = next((value for value in self._dns.txt_values(name) if value.startswith("v=spf1")), None)
        if existing is None:
            self._dns.publish_txt(name, f"v=spf1 {rules} ~all")
            return
        terms = existing.split()
        merged = [terms[0], *(rule for rule in rules.split() if rule not in terms), *terms[1:]]
        others = [value for value in self._dns.txt_values(name) if value != existing]
        self._dns.unpublish(name, "TXT")
        self._dns.publish_txt(name, *others, " ".join(merged))


def _record_name(record_host: str, *, domain: str, host: str) -> str:
    labels = [label for label in (record_host if record_host != "@" else "", host) if label]
    return ".".join([*labels, domain])


def _render(record: dict[str, Any], variables: dict[str, str]) -> dict[str, Any]:
    def substitute(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        missing = set(_TEMPLATE_VARIABLE.findall(value)) - variables.keys()
        if missing:
            raise DomainConnectRejected(f"The apply URL is missing template variables {sorted(missing)}")
        return _TEMPLATE_VARIABLE.sub(lambda match: variables[match[1]], value)

    return {key: substitute(value) for key, value in record.items()}


def _load_template(provider_id: str, service_id: str) -> dict[str, Any]:
    path = TEMPLATE_DIR / f"{provider_id}.{service_id}.json"
    if not path.exists():
        raise DomainConnectRejected(f"No template {provider_id}/{service_id}")
    return json.loads(path.read_text())


def _public_key() -> RSAPublicKey:
    if not settings.DOMAIN_CONNECT_PRIVATE_KEY:
        raise DomainConnectRejected("PostHog has no published signing key")
    private_key = serialization.load_pem_private_key(settings.DOMAIN_CONNECT_PRIVATE_KEY.encode(), password=None)
    assert isinstance(private_key, RSAPrivateKey)
    return private_key.public_key()
