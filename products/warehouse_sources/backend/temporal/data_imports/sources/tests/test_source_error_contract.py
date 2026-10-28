"""Error classification checks for every source in the registry, so that no source needs its own copy of them.

1. Each key of `get_non_retryable_errors()` is a non-empty string, and each value is None or a non-empty string.
2. When the vendor answers every request with 401, and again with 403, the extraction raises an error
   that the pipeline classifies as non-retryable.
3. When the vendor answers every request with 429 or 500, or the connection times out or resets, the
   extraction does not raise an error that the pipeline classifies as non-retryable.

The checks drive the real extraction through the fake network. They classify the error that the source
really raises, with the patterns and the matcher of the pipeline. A source with no credential field is
not held to check 2, because the user cannot fix a 401 from a public API. A source that this test
cannot drive has an entry in a list below, with the reason. An entry that starts to pass must leave its
list, so the lists only get shorter.
"""

import functools
from typing import Any

import pytest

from posthog.dataclasses import frozen

import products.warehouse_sources.backend.temporal.data_imports.sources._load_all  # noqa: F401
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import Any_Source_Errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    _BaseSource,
    error_message_matches,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DatabaseBlockedError,
    NetworkBlockedError,
    RunStopped,
    ScriptedResponse,
    SourceDriver,
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
SOURCE_NAMES = sorted(ALL_SOURCES)
EXTRACTING_SOURCE_NAMES = [name for name in SOURCE_NAMES if not is_stub(ALL_SOURCES[name])]

TEAM_ID = 1
# A source whose first schemas send no request, for example webhook-only schemas, gets this many tries.
MAX_SCHEMAS_TRIED = 5

AUTH_FAILURES: dict[str, ScriptedResponse | BaseException] = {
    "401": ScriptedResponse(status=401),
    "403": ScriptedResponse(status=403),
}
TRANSIENT_FAILURES: dict[str, ScriptedResponse | BaseException] = {
    "429": ScriptedResponse(status=429),
    "500": ScriptedResponse(status=500),
    "read_timeout": TimeoutError("timed out"),
    "connection_reset": ConnectionResetError(104, "Connection reset by peer"),
}
ALL_AUTH_STATUSES = frozenset(AUTH_FAILURES)

# Sources whose errors this test cannot classify. Reasons:
# `driver`: the source imports a driver that opens connections the fake network cannot see.
# `schemas`: `get_schemas` lists no schema for any placeholder config.
# `no-request`: no extraction sends a request for any placeholder config and schema.
# `database`: the extraction reads the application database before its first request.
# `transport`: the extraction opens a connection outside `requests` before its first request.
# `redacted`: the only placeholder config that reaches the vendor holds `1`, and the redaction of
#   secrets masks each `1` in the error text, so the status code in the text no longer reads `401`.
NOT_CHECKABLE: dict[str, str] = {
    "AmazonS3": "schemas",
    "AppStoreConnect": "no-request",
    "AppleSearchAds": "no-request",
    "Attentive": "no-request",
    "AwsAthena": "schemas",
    "AwsDocumentDB": "driver",
    "AzureBlob": "schemas",
    "AzureCostManagement": "no-request",
    "AzureLogAnalytics": "no-request",
    "Baserow": "schemas",
    "BigQuery": "driver",
    "BingAds": "database",
    "Breezometer": "no-request",
    "CiscoDuo": "no-request",
    "ClickHouse": "schemas",
    "CloudflareD1": "schemas",
    "CloudflareR2": "schemas",
    "Convex": "schemas",
    "CosmosDB": "schemas",
    "Coveralls": "no-request",
    "Custom": "schemas",
    "CustomerIO": "no-request",
    "Databricks": "driver",
    "Depot": "no-request",
    "Docusign": "no-request",
    "Dynamics365": "no-request",
    "DynamoDB": "schemas",
    "Elasticsearch": "schemas",
    "FileUpload": "no-request",
    "Firebase": "schemas",
    "Framer": "no-request",
    "GcpCloudBilling": "no-request",
    "Ghost": "no-request",
    "Github": "no-request",
    "GoogleAds": "driver",
    "GoogleAnalytics": "database",
    "GoogleCloudStorage": "schemas",
    "GooglePlayConsole": "no-request",
    "GoogleSearchConsole": "database",
    "GoogleSheets": "schemas",
    "GrafanaIRM": "no-request",
    "Hatchet": "no-request",
    "HelpScout": "database",
    "Hubspot": "database",
    "Instagram": "database",
    "Intercom": "database",
    "Kafka": "driver",
    "Kestra": "no-request",
    "Linear": "database",
    "LinkedinAds": "database",
    "Logicmonitor": "no-request",
    "MSSQL": "driver",
    "MetaAds": "database",
    "Modal": "driver",
    "MongoDB": "driver",
    "Motherduck": "driver",
    "MySQL": "driver",
    "Neo4j": "schemas",
    "Neon": "driver",
    "OpenMeteo": "no-request",
    "OpenWeather": "no-request",
    "Pardot": "database",
    "PinterestAds": "database",
    "PlanetScaleMySQL": "driver",
    "PlanetScalePostgres": "driver",
    "Postgres": "driver",
    "ProofpointTap": "no-request",
    "RedditAds": "database",
    "Redshift": "driver",
    "SFTP": "schemas",
    "Salesforce": "database",
    "SevenShifts": "redacted",
    "Slack": "schemas",
    "SnapchatAds": "database",
    "Snowflake": "driver",
    "Supabase": "driver",
    "TemporalIO": "driver",
    "TikTokAds": "database",
    "Trino": "schemas",
    "TwitterAds": "database",
    "UnityAds": "redacted",
    "Wrike": "no-request",
    "YouTubeAnalytics": "database",
}

# Sources that classify one of 401 and 403 as a credential failure, and retry the other. The value is
# the status that the source classifies, and this test checks that status.
ONE_AUTH_STATUS_CLASSIFIED: dict[str, str] = {
    "AdobeAnalytics": "401",
    "AmazonAds": "401",
    "AssemblyAI": "401",
    "BlandAI": "401",
    "Braintree": "401",
    "Bugherd": "401",
    "CdcOpenData": "403",
    "Chameleon": "403",
    "Clever": "401",
    "Cloudability": "401",
    "Codemagic": "401",
    "CoinGecko": "401",
    "Commercetools": "401",
    "Coupa": "403",
    "Courier": "403",
    "DataForSEO": "401",
    "Discourse": "403",
    "Expo": "401",
    "Faire": "401",
    "FusionAuth": "401",
    "GooglePageSpeedInsights": "403",
    "GoogleWebfonts": "403",
    "Healthchecks": "401",
    "Kickscale": "403",
    "Knowbe4": "401",
    "Linearb": "403",
    "Mailjet": "401",
    "NewsApi": "401",
    "OnePassword": "401",
    "OpnPayments": "401",
    "Optimizely": "401",
    "Plaid": "401",
    "PowerBiAdmin": "401",
    "Razorpay": "401",
    "Rewardful": "401",
    "SharePoint": "401",
    "Shopify": "401",
    # A 401 means no data for one domain, so the source skips it on purpose.
    "Similarweb": "403",
    "SpotlerCRM": "403",
    "TMDb": "401",
    "TrunkIo": "401",
    "Uptimerobot": "403",
    "Waydev": "401",
    "ZapierSupportedStorage": "401",
}

# Sources that classify a credential failure in another way on purpose. Reasons:
# `error-body`: the source reads the failure from the vendor's response body, such as an AWS error code
#   or a GraphQL error, and a bare status has no body to read.
AUTH_CLASSIFIED_ELSEWHERE: dict[str, str] = {
    "AlphaVantage": "error-body",
    "AwsBatch": "error-body",
    "AwsBudgets": "error-body",
    "AwsCloudTrail": "error-body",
    "AwsComputeOptimizer": "error-body",
    "AwsConfig": "error-body",
    "AwsCostAnomalyDetection": "error-body",
    "AwsCostExplorer": "error-body",
    "AwsGlueDataCatalog": "error-body",
    "AwsGuardduty": "error-body",
    "AwsIamAccessAnalyzer": "error-body",
    "AwsMacie": "error-body",
    "AwsOrganizations": "error-body",
    "AwsSagemaker": "error-body",
    "AwsSavingsPlans": "error-body",
    "AwsSecurityHub": "error-body",
    "AwsSes": "error-body",
    "AwsStepFunctions": "error-body",
    "AwsSystemsManager": "error-body",
    "AwsWaf": "error-body",
    "Bettermode": "error-body",
    "Finnworlds": "error-body",
    "LessAnnoyingCRM": "error-body",
    "Railway": "error-body",
    "Skio": "error-body",
    "Spacelift": "error-body",
    "Stripe": "error-body",
    "Stytch": "error-body",
    "TwelveData": "error-body",
    "USCensus": "error-body",
    "UsBea": "error-body",
}

# Sources whose real 401 and 403 errors the pipeline retries until the retry budget runs out.
# Each entry is a defect to fix.
AUTH_FAILURE_NOT_CLASSIFIED: dict[str, str] = {}

# Sources whose real error for a transient failure matches a key on purpose. The value is every such failure.
TRANSIENT_FAILURE_NON_RETRYABLE_ON_PURPOSE: dict[str, frozenset[str]] = {
    # A 429 means that the daily quota of the project is used up.
    "MicrosoftClarity": frozenset({"429"}),
    # A 429 means that the vendor blocked the account after over-use.
    "OpenExchangeRates": frozenset({"429"}),
    # The source retries a 429 itself, and then raises an error that says the daily row quota is used up.
    "Singular": frozenset({"429"}),
}

# Sources whose real error for a transient failure matches a key, so that a short outage disables the sync.
# Each entry is a defect to fix: make the key narrower. The value is every such failure.
TRANSIENT_FAILURE_CLASSIFIED_NON_RETRYABLE: dict[str, frozenset[str]] = {}


@frozen
class Probe:
    """A config and a schema whose extraction sends a request, so that a scripted failure reaches the source."""

    config: Any
    schema_name: str


@frozen
class AuthVerdict:
    # Empty when the test found a probe, or else the reason it found none.
    not_checkable: str = ""
    # The auth statuses whose real error the pipeline classifies as non-retryable, for the best probe.
    classified: frozenset[str] = frozenset()
    probe: Probe | None = None
    # The errors that the pipeline does not classify, for the message of a failed check.
    detail: str = ""


def _is_non_retryable(source: _BaseSource[Any], error: BaseException) -> bool:
    # The same patterns and the same matcher as the pipeline uses, in the activity and in the finalizer.
    return error_message_matches(str(error), {**Any_Source_Errors, **source.get_non_retryable_errors()})


def _has_credential_field(fields: list[Any]) -> bool:
    for field in fields:
        if getattr(field, "secret", False) or getattr(field, "type", None) in ("oauth", "file-upload"):
            return True
        nested = list(getattr(field, "fields", None) or [])
        for option in getattr(field, "options", None) or []:
            nested.extend(getattr(option, "fields", None) or [])
        if _has_credential_field(nested):
            return True
    return False


def _schema_names(source: _BaseSource[Any], config: Any) -> list[str]:
    # A source that asks the vendor for its schema list gets an empty page, so it still names its static schemas.
    with scripted_network(always(ScriptedResponse(json=empty_page_body(None, 0)))):
        try:
            return [schema.name for schema in source.get_schemas(config, team_id=TEAM_ID)]
        except (Exception, RunStopped):
            return []


def _probes(source: _BaseSource[Any]) -> tuple[list[Probe], str]:
    """One probe for each placeholder config that reaches the vendor, or else the reason there is none."""
    probes: list[Probe] = []
    reasons: set[str] = set()
    for config in placeholder_configs(source._config_class):
        schema_names = _schema_names(source, config)
        if not schema_names:
            reasons.add("schemas")
        for schema_name in schema_names[:MAX_SCHEMAS_TRIED]:
            result = SourceDriver(source, config).run(schema_name, always(ScriptedResponse(status=401)))
            if result.requests:
                probes.append(Probe(config=config, schema_name=schema_name))
                break
            if isinstance(result.raised, DatabaseBlockedError):
                reasons.add("database")
            elif isinstance(result.raised, NetworkBlockedError):
                reasons.add("transport")
            else:
                reasons.add("no-request")
    return probes, next((r for r in ("database", "transport", "no-request", "schemas") if r in reasons), "schemas")


def _raised(source: _BaseSource[Any], probe: Probe, answer: ScriptedResponse | BaseException) -> BaseException | None:
    raised = SourceDriver(source, probe.config).run(probe.schema_name, always(answer)).raised
    # The harness ends a run that does not end by itself. The pipeline never sees that error.
    return None if isinstance(raised, RunStopped) else raised


def _describe(raised: BaseException | None) -> str:
    return "no error" if raised is None else f"{type(raised).__name__}: {raised}"


@functools.cache
def auth_verdict(name: str) -> AuthVerdict:
    source = ALL_SOURCES[name]
    if native_driver(source) is not None:
        return AuthVerdict(not_checkable="driver")
    probes, reason = _probes(source)
    if not probes:
        return AuthVerdict(not_checkable=reason)

    # A placeholder value can appear in the error text, where the redaction of secrets masks it. So the
    # verdict is the one of the probe that classifies the most statuses.
    best: AuthVerdict | None = None
    for probe in probes:
        raised = {code: _raised(source, probe, answer) for code, answer in AUTH_FAILURES.items()}
        classified = frozenset(
            code for code, error in raised.items() if error is not None and _is_non_retryable(source, error)
        )
        detail = " | ".join(f"{code}: {_describe(error)}" for code, error in raised.items() if code not in classified)
        if best is None or len(classified) > len(best.classified):
            best = AuthVerdict(classified=classified, probe=probe, detail=detail)
        if classified == ALL_AUTH_STATUSES:
            break
    assert best is not None
    return best


def transient_failures_classified(name: str) -> dict[str, str]:
    """Each transient failure whose real error the pipeline classifies as non-retryable, with that error."""
    verdict = auth_verdict(name)
    if verdict.probe is None:
        return {}
    source = ALL_SOURCES[name]
    raised = {failure: _raised(source, verdict.probe, answer) for failure, answer in TRANSIENT_FAILURES.items()}
    return {
        failure: _describe(error)
        for failure, error in raised.items()
        if error is not None and _is_non_retryable(source, error)
    }


@pytest.mark.parametrize("name", SOURCE_NAMES, ids=str)
def test_non_retryable_errors_are_well_formed(name: str) -> None:
    errors = ALL_SOURCES[name].get_non_retryable_errors()
    assert all(isinstance(key, str) and key.strip() for key in errors), f"{name} has an empty or non-string key."
    # A None value tells the finalizer to show the raw error, where a string replaces it with a friendly message.
    assert all(value is None or (isinstance(value, str) and value.strip()) for value in errors.values()), (
        f"{name} has a message that is not None and not a non-empty string."
    )


@pytest.mark.parametrize("name", EXTRACTING_SOURCE_NAMES, ids=str)
def test_auth_failures_are_non_retryable(name: str) -> None:
    verdict = auth_verdict(name)
    passes = verdict.classified == ALL_AUTH_STATUSES
    if name in NOT_CHECKABLE:
        assert not passes, f"{name} passes now. Remove it from NOT_CHECKABLE."
        return
    assert not verdict.not_checkable, (
        f"{name}: the test cannot drive the source (`{verdict.not_checkable}`). Add it to NOT_CHECKABLE."
    )
    if name in ONE_AUTH_STATUS_CLASSIFIED:
        expected = frozenset({ONE_AUTH_STATUS_CLASSIFIED[name]})
        assert not passes, f"{name} passes now. Remove it from ONE_AUTH_STATUS_CLASSIFIED."
        assert verdict.classified == expected, (
            f"{name}: the pipeline retries the real {ONE_AUTH_STATUS_CLASSIFIED[name]} error: {verdict.detail}"
        )
        return
    if name in AUTH_CLASSIFIED_ELSEWHERE or name in AUTH_FAILURE_NOT_CLASSIFIED:
        assert not passes, f"{name} passes now. Remove it from its list."
        return
    if not passes and not _has_credential_field(ALL_SOURCES[name].get_source_config.fields):
        return
    assert passes, (
        f"{name}: a vendor that answers every request with the status gives {verdict.detail}. The source must "
        "raise an error that matches a key of `get_non_retryable_errors()`."
    )


@pytest.mark.parametrize("name", EXTRACTING_SOURCE_NAMES, ids=str)
def test_transient_failures_stay_retryable(name: str) -> None:
    classified = transient_failures_classified(name)
    listed = TRANSIENT_FAILURE_NON_RETRYABLE_ON_PURPOSE | TRANSIENT_FAILURE_CLASSIFIED_NON_RETRYABLE
    if name in listed:
        expected = listed[name]
        assert expected <= classified.keys(), (
            f"{name}: {sorted(expected - classified.keys())} stay retryable now. Update its list entry."
        )
        assert classified.keys() == expected, (
            f"{name}: the pipeline also stops on failures that its list entry does not name: "
            f"{ {failure: error for failure, error in classified.items() if failure not in expected} }"
        )
        return
    assert classified == {}, (
        f"{name}: a transient vendor failure raises an error that matches a key of `get_non_retryable_errors()`, "
        f"so a short outage disables the sync: {classified}"
    )


@pytest.mark.parametrize(
    "allowlist",
    [
        NOT_CHECKABLE,
        ONE_AUTH_STATUS_CLASSIFIED,
        AUTH_CLASSIFIED_ELSEWHERE,
        AUTH_FAILURE_NOT_CLASSIFIED,
        TRANSIENT_FAILURE_NON_RETRYABLE_ON_PURPOSE,
        TRANSIENT_FAILURE_CLASSIFIED_NON_RETRYABLE,
    ],
    ids=[
        "not_checkable",
        "one_auth_status",
        "auth_elsewhere",
        "auth_defect",
        "transient_on_purpose",
        "transient_defect",
    ],
)
def test_allowlists_name_only_extracting_sources(allowlist: dict[str, Any]) -> None:
    assert sorted(allowlist.keys() - set(EXTRACTING_SOURCE_NAMES)) == []


@pytest.mark.parametrize(
    "name,message",
    [
        (
            "Appdynamics",
            "AppDynamics OAuth token request failed. Check your API client name, client secret, and account name.",
        ),
        ("IP2Whois", "IP2WHOIS API error [10000]: Invalid API key."),
        ("IP2Whois", "IP2WHOIS API error: unexpected status 418"),
        ("Marketo", "Marketo authentication failed: status=401, body={}"),
        ("Marketo", "Marketo authentication failed: status=401, path=/rest/v1/leads.json, body={}"),
        ("Marketo", "Marketo authentication failed: no access token in response ({})"),
    ],
)
def test_narrowed_keys_still_match_permanent_errors(name: str, message: str) -> None:
    assert error_message_matches(message, ALL_SOURCES[name].get_non_retryable_errors())
