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

**Sequencing, which is the part that bites.** Once the service is on, a key that is NOT in it
raises `SecretMissingError` — the client does not fall back to settings, by design, because a
silent fallback is how a half-finished rollout looks exactly like a working one. So a call site
moves to this module only after its key exists in the service for every environment that runs it.
Migrate one key at a time, in that order, not the other way round.
"""

from __future__ import annotations

import requests
from urllib3.util.retry import Retry

from posthog.integration_secrets import client as integration_secrets_client
from posthog.integration_secrets.callers import IntegrationCaller
from posthog.integration_secrets.client import RotatingSecret

from products.warehouse_sources.backend.temporal.data_imports.sources.common.http import make_tracked_session

CALLER = IntegrationCaller.WAREHOUSE_SOURCES


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


def get_secret(key: str) -> str:
    """One PostHog-owned credential, by the name it has in the service and in settings."""
    return _client.get(key, CALLER)


def get_secrets(keys: list[str]) -> dict[str, str]:
    """Several at once, in a single request — a source usually needs an id and a secret together."""
    return _client.get_many(keys, CALLER)


def get_secret_with_incoming(key: str) -> RotatingSecret:
    """The live value plus the staged replacement, while a rotation is in flight.

    For a source that can retry against the third party: try `current`, and on an auth failure
    retry with `incoming`. That covers the window where the credential has already been rotated at
    the provider but the promotion has not happened here yet — the one case where a rotation is
    visible to a source at all.
    """
    return _client.get_with_incoming(key, CALLER)
