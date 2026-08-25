"""How warehouse sources read PostHog's own credentials.

These are the OAuth app client ids/secrets, developer tokens, and API keys PostHog owns — the
ones a source presents as *itself*, not the per-team credentials a customer connected. Today a
source reads them straight off Django settings (`settings.GOOGLE_ADS_DEVELOPER_TOKEN`), which
means rotating one is a charts PR and a restart of everything that mounts it.

This module is the single place sources go instead. It binds the two things every warehouse call
would otherwise repeat, and gets wrong differently each time:

- **The caller identity.** `IntegrationCaller.WAREHOUSE_SOURCES` is what the service writes to its
  audit log, so it is how "who read this credential" gets answered. Pinning it here means a new
  source cannot label its reads as something else by copying the wrong line.
- **The transport.** A session that meters and logs like the rest of a job's HTTP traffic, with
  two properties that are easy to lose and expensive to lose: no sample capture, and no egress
  proxy. Both are explained on `_session` below.

Reading through here changes nothing until a key is actually moved into the service. With the
service off (self-hosted, local development, the flag disabled) the client reads the same
`os.environ`/settings value the source reads today, so a migrated call site behaves identically.

**Sequencing.** Call sites and keys cannot move at the same instant, and the service is already
live on the data-warehouse worker — so `_resolve_one` below keeps reading settings for a key that
has not reached the service yet, counting every time it does. That makes the order of the two
moves not matter, and makes "is the rollout finished?" a metric rather than a belief. It is
temporary; the removal condition is on `_resolve_one`.
"""

from __future__ import annotations

import os

from django.conf import settings

import requests
import structlog
from prometheus_client import Counter
from urllib3.util.retry import Retry

from posthog.integration_secrets import client as integration_secrets_client
from posthog.integration_secrets.callers import IntegrationCaller
from posthog.integration_secrets.client import RotatingSecret
from posthog.integration_secrets.errors import SecretMissingError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

logger = structlog.get_logger(__name__)

CALLER = IntegrationCaller.WAREHOUSE_SOURCES

SETTINGS_FALLBACK_COUNTER = Counter(
    "posthog_warehouse_integration_secret_settings_fallback_total",
    "Platform credential reads the integration service could not serve, by what happened instead",
    # outcome="settings": the key is still only in settings, so the rollout isn't finished for it.
    # outcome="unset": the credential isn't configured anywhere, which is the normal state of an
    # integration a deployment doesn't use. Separated because only the first is a rollout gap.
    labelnames=["key", "outcome"],
)


def _build_session() -> requests.Session:
    """The tracked session credential reads go over, with two deliberate departures.

    `capture=False` — **required, not a preference.** The response body on this path is the
    credential in plaintext. HTTP sample capture stores request and response bodies in Redis so
    they can be read back while debugging a source, and the name-based scrubbers cannot recognise
    a value they have never seen. Metering and the log line survive; only the body capture is off.

    `trust_env=False` — the integration service is an internal, in-cluster address. Warehouse
    outbound traffic goes through the Smokescreen egress proxy, which re-resolves every hop and
    blocks internal and metadata hosts. That is exactly right for a customer's API and exactly
    wrong here: left on, every credential read would be handed to a proxy whose job is to refuse
    it. This is the same reason `posthog.security.outbound_proxy.internal_requests` exists, and
    the reason we cannot simply reuse a plain tracked session.

    `Retry(total=0)` — the client holds no cache, so there is no last known good and a retry here
    would only add latency in front of a failure Temporal already retries with backoff. It matches
    the shared internal session, whose adapter also does not retry. (`DEFAULT_RETRY` would be a
    no-op anyway, since it retries only GET/HEAD/OPTIONS and this is a POST — stated explicitly so
    it stays true if that policy changes.)
    """
    session = make_tracked_session(retry=Retry(total=0), capture=False)
    session.trust_env = False
    return session


# One session for the process, like the shared internal one. The tracked adapter reads the job
# context from contextvars at request time, so a single session still labels each request with the
# team and source it was made for.
_session = _build_session()
_client = integration_secrets_client.IntegrationSecretsClient(session=_session)


def _from_settings(key: str) -> str | None:
    """The value this key had before the service existed, or None."""
    return (os.environ.get(key) or getattr(settings, key, "")) or None


def _resolve_one(key: str) -> str:
    """One credential, falling back to settings while the key is still on its way into the service.

    TEMPORARY, and the removal condition is exact: when
    `posthog_warehouse_integration_secret_settings_fallback_total` has been zero across a full sync
    cycle, every key has moved and this function collapses back to `_client.get`.

    It exists because the call sites and the keys cannot move at the same instant. The service is
    already live on the data-warehouse worker, so without this, migrating a call site whose key is
    not in the service yet fails every sync for that source the moment it deploys — for Google Ads,
    Analytics, Search Console, Sheets, HubSpot, Salesforce, TikTok and Bing at once. The same code
    also runs in the web app, where the service is not configured at all.

    It is not the silent fallback the client refuses to have. That one is dangerous because it
    hides a half-finished rollout behind apparent success; this one names the key, counts it, and
    is the thing you watch to know when the rollout is finished.

    Only a MISSING key falls back, and the two exclusions are the point:

    - A key in **recovery** must not fall back. Recovery means the credential is known-burned; the
      settings copy is the very value that was burned, so serving it would turn the kill switch
      into a no-op — the one failure mode worse than the sync stopping.
    - An **unreachable service** must not fall back. There is no last known good to fall back to,
      and treating an outage as "the key isn't there" would mask it as a rollout gap.
    """
    try:
        return _client.get(key, CALLER)
    except SecretMissingError:
        value = _from_settings(key)
        if value is not None:
            SETTINGS_FALLBACK_COUNTER.labels(key=key, outcome="settings").inc()
            logger.warning("warehouse_integration_secret.settings_fallback", key=key)
            return value

        # Configured nowhere. Before this migration the call site read `settings.X` and got the
        # empty string its default provides, and an unusable credential surfaced later as a
        # rejection from the vendor. Keep exactly that: this change moves where a credential comes
        # from, and must not also change what happens when there isn't one. Raising here instead
        # would alter behaviour for every deployment that doesn't use a given integration —
        # self-hosted, local development, and every test that never set it — which is a much wider
        # blast radius than the migration itself, and no part of what it is for.
        SETTINGS_FALLBACK_COUNTER.labels(key=key, outcome="unset").inc()
        logger.debug("warehouse_integration_secret.unset", key=key)
        return ""


def get_secret(key: str) -> str:
    """One PostHog-owned credential, by the name it has in the service and in settings."""
    return _resolve_one(key)


def get_secrets(keys: list[str]) -> dict[str, str]:
    """Several at once, in a single request — a source usually needs an id and a secret together.

    The batch resolves in one request. If any key in it is missing, the batch cannot say which,
    so the keys are re-resolved one at a time to let the fallback above apply per key. That costs
    an extra round trip only while a source is mid-migration, and disappears with the fallback.
    """
    try:
        return _client.get_many(keys, CALLER)
    except SecretMissingError:
        return {key: _resolve_one(key) for key in keys}


def get_secret_with_incoming(key: str) -> RotatingSecret:
    """The live value plus the staged replacement, while a rotation is in flight.

    For a source that can retry against the third party: try `current`, and on an auth failure
    retry with `incoming`. That covers the window where the credential has already been rotated at
    the provider but the promotion has not happened here yet — the one case where a rotation is
    visible to a source at all.
    """
    return _client.get_with_incoming(key, CALLER)
