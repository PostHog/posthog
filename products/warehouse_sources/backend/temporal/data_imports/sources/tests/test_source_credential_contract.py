"""Credential probe checks for every source in the registry, so that no source needs its own copy of them.

Each source that overrides `validate_credentials` runs against a fake vendor that gives the same answer
to every request. Each secret field of the config holds a unique sentinel value.

1. A `401` answer gives `(False, message)`, with a message that is not empty.
2. A `403` answer gives the same, unless the source accepts a key that lacks one scope.
3. A `500` answer and a dropped connection give the same.
4. A `200` answer gives `(True, ...)`.
5. No answer above makes the probe raise. The API calls the probe while a person creates a source. A
   probe that raises shows them a generic message, or a server error.
6. No message and no raised error contains a sentinel, so the probe never echoes a secret.

A source that this test cannot drive has an entry in an allowlist below, with the reason. That source
keeps its own test for the check. An entry that starts to pass must leave its list, so the lists only
get shorter.
"""

import functools
import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

import requests

from posthog.dataclasses import frozen

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.presentation.views.external_data_source.helpers import (
    get_nonsensitive_and_sensitive_field_names,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import _BaseSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import is_config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    RunStopped,
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.tests.contract_harness import (
    empty_page_body,
    is_stub,
    native_driver,
    placeholder_configs,
)

ALL_SOURCES: dict[str, _BaseSource[Any]] = {
    str(source_type): source for source_type, source in SourceRegistry.get_all_sources().items()
}
PROBING_SOURCE_NAMES = sorted(
    name
    for name, source in ALL_SOURCES.items()
    if not is_stub(source) and type(source).validate_credentials is not _BaseSource.validate_credentials
)

TEAM_ID = 1
PASS = "pass"
SENTINEL = "contractsecret"

Answer = Callable[[RecordedRequest], ScriptedResponse]

UNAUTHORIZED = "401"
FORBIDDEN = "403"
SERVER_ERROR = "500"
CONNECTION_ERROR = "connection"
OK = "200"
FAILURE_ANSWERS: dict[str, Answer] = {
    UNAUTHORIZED: always(ScriptedResponse(status=401, json={"error": "unauthorized"})),
    FORBIDDEN: always(ScriptedResponse(status=403, json={"error": "forbidden"})),
    SERVER_ERROR: always(ScriptedResponse(status=500, json={"error": "server error"})),
    CONNECTION_ERROR: always(requests.ConnectionError("contract connection refused")),
}
# Generic bodies that most probes accept, because a probe reads the status or one common key.
OK_ANSWERS: tuple[Answer, ...] = (
    always(ScriptedResponse(json={})),
    always(ScriptedResponse(json=[])),
    always(ScriptedResponse(json=empty_page_body(None, 0))),
)

# Sources whose probe this test cannot drive. Reasons:
# `driver`: the source imports a driver that opens connections the fake network cannot see.
# `database`: the probe reads the application database, for example an OAuth integration row.
# `config`: no request reaches the fake network. The probe rejects every placeholder config, or it
#   connects without urllib3.
NOT_CHECKABLE: dict[str, str] = {
    "Ably": "config",
    "AmazonS3": "config",
    "AppStoreConnect": "config",
    "AppleSearchAds": "config",
    "AwsDocumentDB": "driver",
    "AzureBlob": "config",
    "AzureCostManagement": "config",
    "BigQuery": "driver",
    "BingAds": "database",
    "Breezometer": "config",
    "Calendarific": "config",
    "CdcOpenData": "config",
    "CircleciInsights": "config",
    "CiscoDuo": "config",
    "Clay": "config",
    "CloudflareR2": "config",
    "Convex": "config",
    "Coveralls": "config",
    "Criteo": "config",
    "Custom": "config",
    "Databricks": "driver",
    "Depot": "config",
    "Docusign": "config",
    "Dynamics365": "config",
    "FileUpload": "config",
    "Firebase": "config",
    "Framer": "config",
    "GcpCloudBilling": "config",
    "Ghost": "config",
    "Github": "config",
    "GoogleAds": "driver",
    "GoogleAnalytics": "database",
    "GoogleCloudStorage": "config",
    "GooglePlayConsole": "config",
    "GoogleSearchConsole": "database",
    "GoogleSheets": "config",
    "GrafanaIRM": "config",
    "Hatchet": "config",
    "HelpScout": "database",
    "Instagram": "database",
    "Intercom": "database",
    "Kafka": "driver",
    "Kestra": "config",
    "Linear": "database",
    "LinkedinAds": "database",
    "Logicmonitor": "config",
    "MSSQL": "driver",
    "Modal": "driver",
    "MongoDB": "driver",
    "Motherduck": "driver",
    "MySQL": "driver",
    "NagerDate": "config",
    "Neo4j": "config",
    "Neon": "driver",
    "OpenMeteo": "config",
    "OpenWeather": "config",
    "Pardot": "database",
    "PinterestAds": "database",
    "PlanetScaleMySQL": "driver",
    "PlanetScalePostgres": "driver",
    "Postgres": "driver",
    "RedditAds": "database",
    "Redshift": "driver",
    "SFTP": "config",
    "Sevdesk": "config",
    "SnapchatAds": "database",
    "Snowflake": "driver",
    "Steam": "config",
    "Supabase": "driver",
    "TemporalIO": "driver",
    "TikTokAds": "database",
    "TwitterAds": "database",
    "Whop": "config",
    "Wrike": "config",
    "YouTubeAnalytics": "database",
}

# Sources that give `True` for an answer other than a `200`, on purpose. Reasons:
# `scope`: a `403` means a valid key that lacks one scope. A person can grant only the scopes of the
#   tables they sync, so the probe accepts the key.
# `status`: only an auth rejection proves a bad key, so the probe accepts every other status.
# `transient`: an unreachable API must not block source creation. The sync reports a bad key later.
# `body`: the vendor tells a bad key apart by the body of its answer, which the generic answer lacks.
ACCEPTED: dict[str, dict[str, str]] = {
    UNAUTHORIZED: {
        "Algolia": "body",
    },
    FORBIDDEN: {
        "Acculynx": "scope",
        "Adapty": "scope",
        "Adyen": "scope",
        "Aftership": "scope",
        "Algolia": "body",
        "Anthropic": "scope",
        "Appcues": "scope",
        "Appfigures": "scope",
        "Appfollow": "scope",
        "Arcade": "scope",
        "Argocd": "scope",
        "Ashby": "scope",
        "Astronomer": "scope",
        "AwsGuardduty": "scope",
        "AwsInspector": "scope",
        "BambooHR": "scope",
        "Beamer": "scope",
        "Beehiiv": "scope",
        "BetterStack": "scope",
        "BigCommerce": "scope",
        "Blueshift": "scope",
        "Braze": "scope",
        "Brex": "scope",
        "Buildkite": "scope",
        "Buttondown": "scope",
        "CanvasLms": "scope",
        "Census": "scope",
        "Checkly": "scope",
        "CiscoMeraki": "scope",
        "Clarifai": "scope",
        "Clevertap": "scope",
        "ClickhouseCloud": "scope",
        "Cloudsmith": "scope",
        "Clover": "scope",
        "Codefresh": "scope",
        "CoinApi": "scope",
        "Confluence": "scope",
        "ConfluentCloud": "scope",
        "ConvertKit": "scope",
        "Cortex": "scope",
        "Datahub": "scope",
        "Dbt": "scope",
        "Deel": "scope",
        "Develocity": "scope",
        "DevinAI": "scope",
        "Discourse": "scope",
        "Drata": "scope",
        "Dynatrace": "scope",
        "ElevenLabs": "scope",
        "Eppo": "scope",
        "Finage": "scope",
        "Finnhub": "scope",
        "Fintoc": "scope",
        "FireworksAI": "scope",
        "Flagsmith": "scope",
        "Folk": "scope",
        "Freshcaller": "scope",
        "Freshchat": "scope",
        "Freshdesk": "scope",
        "Freshsales": "scope",
        "Freshservice": "scope",
        "Front": "scope",
        "G2": "scope",
        "Gerrit": "scope",
        "Givebutter": "scope",
        "Gong": "scope",
        "Grafana": "scope",
        "Granola": "scope",
        "GrowthBook": "scope",
        "Harness": "scope",
        "Hex": "scope",
        "HeyGen": "scope",
        "HiBob": "scope",
        "Hookdeck": "scope",
        "IncidentIo": "scope",
        "Insightly": "scope",
        "Instana": "scope",
        "Instantly": "scope",
        "Invoiceninja": "scope",
        "JfrogArtifactory": "scope",
        "Jira": "scope",
        "Jumpcloud": "scope",
        "K6Cloud": "scope",
        "Kandji": "scope",
        "Kernel": "scope",
        "Klarna": "scope",
        "Knowbe4": "scope",
        "Kustomer": "scope",
        "Lago": "scope",
        "Lattice": "scope",
        "LaunchDarkly": "scope",
        "Leexi": "scope",
        "LexwareOffice": "scope",
        "Lightdash": "scope",
        "Lob": "scope",
        "Logrocket": "scope",
        "LogzIO": "scope",
        "Lokalise": "scope",
        "MailerSend": "scope",
        "Mercury": "scope",
        "Metabase": "scope",
        "Mezmo": "scope",
        "MightyNetworks": "scope",
        "Mixpanel": "scope",
        "Mollie": "scope",
        "Mux": "scope",
        "NewYorkTimes": "scope",
        "OctopusDeploy": "scope",
        "Okendo": "scope",
        "Okta": "scope",
        "Omni": "scope",
        "Onfleet": "scope",
        "OpenAI": "scope",
        "OpenAIAds": "scope",
        "Opencorporates": "scope",
        "Opsgenie": "scope",
        "Optimizely": "scope",
        "Oura": "scope",
        "PagerDuty": "scope",
        "Paymongo": "scope",
        "Perigon": "scope",
        "Persona": "scope",
        "Picqer": "scope",
        "Pinecone": "scope",
        "Pipedrive": "scope",
        "Pipeliner": "scope",
        "Productboard": "scope",
        "Productive": "scope",
        "PromptingCompany": "scope",
        "ProofpointTap": "scope",
        "Propertyware": "scope",
        "Qonto": "scope",
        "Qualtrics": "scope",
        "QualysVmdr": "scope",
        "Raygun": "scope",
        "RetellAI": "scope",
        "RevolutMerchant": "scope",
        "Rippling": "scope",
        "Rootly": "scope",
        "RudderStack": "scope",
        "RunPod": "scope",
        "SafetyCulture": "scope",
        "Sanity": "scope",
        "Scaleway": "scope",
        "Secureframe": "scope",
        "SendGrid": "scope",
        "Sentinelone": "scope",
        "ServiceNow": "scope",
        "SigNoz": "scope",
        "Sim": "scope",
        "Slash": "scope",
        "Sleekplan": "scope",
        "SolarwindsServiceDesk": "scope",
        "SonarCloud": "scope",
        "SparkPost": "scope",
        "SplitIo": "scope",
        "Squadcast": "scope",
        "Square": "scope",
        "Squarespace": "scope",
        "Statsig": "scope",
        "SumoLogic": "scope",
        "Superwall": "scope",
        "Swarmia": "scope",
        "Tailscale": "scope",
        "Tempo": "scope",
        "Thinkific": "scope",
        "ThinkificCourses": "scope",
        "TogetherAI": "scope",
        "TripleWhale": "scope",
        "Turso": "scope",
        "Twenty": "scope",
        "Umami": "scope",
        "Unleash": "scope",
        "Veracode": "scope",
        "Vimeo": "scope",
        "Webflow": "scope",
        "Wix": "scope",
        "WooCommerce": "scope",
        "WorkOS": "scope",
        "Workable": "scope",
        "Xendit": "scope",
        "Xmatters": "scope",
        "Ynab": "scope",
        "Yoco": "scope",
        "YouSign": "scope",
    },
    SERVER_ERROR: {
        "Deel": "status",
        "Elasticemail": "body",
        "Front": "status",
        "HiBob": "status",
        "Kustomer": "status",
        "Lattice": "status",
        "Mollie": "status",
        "NewYorkTimes": "status",
        "Optimizely": "status",
        "Rippling": "status",
        "Singlestore": "transient",
        "TyntecSMS": "status",
        "Upstash": "transient",
    },
    CONNECTION_ERROR: {
        "Singlestore": "transient",
        "Upstash": "transient",
    },
}

# Sources whose probe rejects every generic `200` body, because it reads a vendor-specific key.
OK_NEEDS_VENDOR_BODY: set[str] = {
    "AbnormalSecurity",
    "Adapty",
    "AdobeAnalytics",
    "Ahrefs",
    "AmazonCloudWatch",
    "Anvil",
    "Apollo",
    "Arcade",
    "Ashby",
    "Automox",
    "Avalara",
    "AwsAthena",
    "AwsBudgets",
    "AwsComputeOptimizer",
    "AwsCostAndUsageReport",
    "AzureApplicationInsights",
    "Bettermode",
    "BillCom",
    "BingWebmasterTools",
    "Braintree",
    "Braintrust",
    "BrowseAI",
    "BuildBetter",
    "ChartHop",
    "CircleCI",
    "Clarifai",
    "ClickHouse",
    "ClickUp",
    "Cloudflare",
    "DataForSEO",
    "Deepsource",
    "Etsy",
    "Expo",
    "Fieldpulse",
    "GainsightCs",
    "Getdx",
    "GrowthBook",
    "Gusto",
    "Harness",
    "Infisical",
    "Komodor",
    "Kubecost",
    "Lacework",
    "LexwareOffice",
    "Lightfield",
    "Logrocket",
    "Monday",
    "NewRelic",
    "Nuget",
    "Octolens",
    "OneSignal",
    "Outbrain",
    "Packagist",
    "PayFit",
    "PgAnalyze",
    "Pinecone",
    "Plain",
    "PromptWatch",
    "Qdrant",
    "Railway",
    "ReferralHero",
    "RevenueCat",
    "RevolutMerchant",
    "SageIntacct",
    "Serpstat",
    "Singular",
    "Slack",
    "Snowplow",
    "Sonarqube",
    "Sourcegraph",
    "Spacelift",
    "Speedcurve",
    "Squadcast",
    "TawkTo",
    "Trino",
    "TrustPilot",
    "Turso",
    "Twitter",
    "Uptimerobot",
    "VWO",
    "WeightsAndBiases",
    "WorldBank",
    "Yotpo",
    "YoutubeData",
}

# Sources whose probe raises for these answers. Each entry is a defect to fix: the probe must return
# `(False, message)`. The value lists the answers that raise.
RAISES: dict[str, str] = {}

# Sources whose probe returns no message for these answers. Each entry is a defect to fix: the person
# sees a generic message that does not say what is wrong.
NO_MESSAGE: dict[str, str] = {}

# Sources whose message or raised error contains a secret from the config. Each entry is a defect to fix.
LEAKS_SECRET: set[str] = set()


@frozen
class Outcome:
    valid: bool | None = None
    message: Any = None
    raised: BaseException | None = None
    requests: int = 0
    blocked_database_reads: int = 0


@frozen
class Probe:
    """`status` is `pass`, or the reason that the source is not checkable."""

    status: str
    outcomes: dict[str, Outcome] = dataclasses.field(default_factory=dict)


def _with_sentinels(config: Any, sensitive: set[str], counter: list[int], inside_secret: bool = False) -> Any:
    changes: dict[str, Any] = {}
    for field in dataclasses.fields(config):
        value = getattr(config, field.name)
        secret = inside_secret or field.name in sensitive
        if is_config(value):
            changes[field.name] = _with_sentinels(value, sensitive, counter, secret)
        elif secret and isinstance(value, str):
            counter[0] += 1
            changes[field.name] = f"{SENTINEL}{counter[0]}{value}"
    return dataclasses.replace(config, **changes) if changes else config


def _sentinel_configs(source: _BaseSource[Any]) -> list[Any]:
    sensitive = get_nonsensitive_and_sensitive_field_names(source.get_source_config.fields).sensitive
    return [_with_sentinels(config, sensitive, [0]) for config in placeholder_configs(source._config_class)]


def _call(source: _BaseSource[Any], config: Any, answer: Answer) -> Outcome:
    valid: bool | None = None
    message: Any = None
    raised: BaseException | None = None
    with scripted_network(answer) as network:
        try:
            valid, message = source.validate_credentials(config, TEAM_ID)
        except (Exception, RunStopped) as error:
            raised = error
    return Outcome(
        valid=valid,
        message=message,
        raised=raised,
        requests=len(network.requests_log),
        blocked_database_reads=network.blocked_database_reads,
    )


@functools.cache
def _probe(name: str) -> Probe:
    source = ALL_SOURCES[name]
    if native_driver(source) is not None:
        return Probe(status="driver")

    # A background thread can try a connection while the probe runs, so blocked connections give no reason.
    reason = "config"
    for config in _sentinel_configs(source):
        unauthorized = _call(source, config, FAILURE_ANSWERS[UNAUTHORIZED])
        if not unauthorized.requests:
            reason = "database" if unauthorized.blocked_database_reads else reason
            continue
        outcomes = {UNAUTHORIZED: unauthorized}
        for outcome, answer in FAILURE_ANSWERS.items():
            if outcome != UNAUTHORIZED:
                outcomes[outcome] = _call(source, config, answer)
        for answer in OK_ANSWERS:
            outcomes[OK] = _call(source, config, answer)
            if outcomes[OK].valid is True:
                break
        return Probe(status=PASS, outcomes=outcomes)
    return Probe(status=reason)


def _checked_probe(name: str) -> Probe | None:
    probe = _probe(name)
    if name in NOT_CHECKABLE:
        assert probe.status != PASS, f"{name} passes now. Remove it from NOT_CHECKABLE."
        return None
    assert probe.status == PASS, (
        f"{name}: the credential probe gives `{probe.status}` for every placeholder config. Add the source "
        "to NOT_CHECKABLE with the reason."
    )
    return probe


def _listed(table: dict[str, str], name: str) -> set[str]:
    return set(table.get(name, "").split())


@pytest.mark.parametrize("outcome", list(FAILURE_ANSWERS))
@pytest.mark.parametrize("name", PROBING_SOURCE_NAMES, ids=str)
def test_failure_answer_gives_invalid_with_a_message(name: str, outcome: str) -> None:
    probe = _checked_probe(name)
    if probe is None:
        return
    result = probe.outcomes[outcome]
    if outcome in _listed(RAISES, name):
        assert result.raised is not None, f"{name} does not raise for `{outcome}` now. Remove `{outcome}` from RAISES."
        return
    assert result.raised is None, f"{name}: the probe raises {result.raised!r} for a `{outcome}` answer."

    if name in ACCEPTED[outcome]:
        assert result.valid is True, f"{name} rejects a `{outcome}` answer now. Remove it from ACCEPTED[{outcome!r}]."
        return
    assert result.valid is False, f"{name}: the probe gives {result.valid!r} for a `{outcome}` answer."

    has_message = isinstance(result.message, str) and bool(result.message.strip())
    if outcome in _listed(NO_MESSAGE, name):
        assert not has_message, f"{name} gives a message for `{outcome}` now. Remove `{outcome}` from NO_MESSAGE."
        return
    assert has_message, f"{name}: the probe gives no message for a `{outcome}` answer, so the person cannot act on it."


@pytest.mark.parametrize("name", PROBING_SOURCE_NAMES, ids=str)
def test_ok_answer_gives_valid(name: str) -> None:
    probe = _checked_probe(name)
    if probe is None:
        return
    result = probe.outcomes[OK]
    if name in OK_NEEDS_VENDOR_BODY:
        assert result.valid is not True, f"{name} accepts a generic body now. Remove it from OK_NEEDS_VENDOR_BODY."
        return
    assert result.raised is None, f"{name}: the probe raises {result.raised!r} for a `200` answer."
    assert result.valid is True, (
        f"{name}: the probe rejects every generic `200` body. Add the source to OK_NEEDS_VENDOR_BODY if it "
        "reads a vendor-specific key."
    )


@pytest.mark.parametrize("name", PROBING_SOURCE_NAMES, ids=str)
def test_probe_does_not_echo_a_secret(name: str) -> None:
    probe = _checked_probe(name)
    if probe is None:
        return
    texts = [str(result.message) for result in probe.outcomes.values()]
    texts += [str(result.raised) for result in probe.outcomes.values() if result.raised is not None]
    leaks = any(SENTINEL in text for text in texts)
    if name in LEAKS_SECRET:
        assert leaks, f"{name} does not echo a secret now. Remove it from LEAKS_SECRET."
        return
    assert not leaks, f"{name}: a probe message or error contains a secret value from the config."


@pytest.mark.parametrize(
    "allowlist",
    [
        set(NOT_CHECKABLE),
        OK_NEEDS_VENDOR_BODY,
        set(RAISES),
        set(NO_MESSAGE),
        LEAKS_SECRET,
        *(set(ACCEPTED[outcome]) for outcome in FAILURE_ANSWERS),
    ],
    ids=["not_checkable", "vendor_body", "raises", "no_message", "leaks", *(f"accepted_{o}" for o in FAILURE_ANSWERS)],
)
def test_allowlists_name_only_checked_sources(allowlist: set[str]) -> None:
    assert sorted(allowlist - set(PROBING_SOURCE_NAMES)) == []


@pytest.mark.parametrize("table", [RAISES, NO_MESSAGE], ids=["raises", "no_message"])
def test_allowlists_name_only_failure_answers(table: dict[str, str]) -> None:
    assert sorted({outcome for name in table for outcome in _listed(table, name)} - set(FAILURE_ANSWERS)) == []
