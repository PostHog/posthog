# Network egress audit — default test suite

Detector: `tools/network-audit/pytest_network_audit.py` (socket-level, flags any `connect()` to a globally-routable IP, attributed to the triggering test).

## CI assessment (the real number)

Ran in CI on PR #64270 (record-only, full backend matrix via `run-ci-backend`). Backend CI was **green** — the change broke nothing. Merged 36 per-shard reports:

**137 flagged events across 81 distinct tests, 11 external hosts.** (The local sample found 7 — as expected, the full suite is far worse.)

| Host                                                                                   | events | what it is                                                                                                                                             |
| -------------------------------------------------------------------------------------- | -----: | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `billing.posthog.com`                                                                  |     92 | **dominant** — billing + agentic_provisioning tests call the real billing service (58 distinct tests). Almost certainly a missing global billing mock. |
| `sts.amazonaws.com`                                                                    |     23 | AWS STS — boto3 credential resolution (batch exports / S3)                                                                                             |
| `openaipublic.blob.core.windows.net`                                                   |      8 | `tiktoken` downloading its BPE vocab on first use (hogai / billing / demo tests). Fix: pre-cache / `TIKTOKEN_CACHE_DIR`.                               |
| `us.i.posthog.com`                                                                     |      4 | analytics — survived the seal (background/batch sends + the proxy live test)                                                                           |
| `*.s3.amazonaws.com`                                                                   |      4 | real S3 (batch export file downloads)                                                                                                                  |
| `api.stripe.com`                                                                       |      2 | the StripeClient transitive leak (confirmed earlier)                                                                                                   |
| `publicsuffix.org` / `api.github.com` / `iam.amazonaws.com` / `marketplace.vercel.com` | 1 each | tldextract / GitHub repos API / AWS IAM / Vercel integration                                                                                           |

**Caveat — Modal:** no `*.modal.com` egress here, because `MODAL_TOKEN_ID` is only injected when the PR changes tasks-temporal code (`ci-backend.yml` gates it on `tasks_temporal`). This PR doesn't, so Modal tests ran mocked. The Modal dependency is real but _conditional on the change set_ — a run touching `products/tasks` is needed to capture it.

Merged report + a ready `baseline.json` (82 test+host entries) are in `out/` (gitignored). That baseline is what the enforce-phase PR will ship to ratchet on new violations.

## Scope of this run

- Ran the sensor (record-only) over **76 candidate files** — test files that both import a network client (`requests`/`httpx`/`aiohttp`/`boto3`) _and_ contain a real external URL. That expanded to **3,868 test cases**, 8.5 min wall-clock, one local process against the running dev infra.
- This is **not** a full-suite run. It does not prove the other ~2,600 test files are clean — see "Systemic finding" below for why the real number is likely higher.

## Result: 7 tests made live outbound calls, across 4 hosts

None of them are tagged `requires_secrets` or otherwise isolated.

### A. Intentional external integration test sitting in the default suite (1)

| Test                                                                                                               | Host                   |
| ------------------------------------------------------------------------------------------------------------------ | ---------------------- |
| `posthog/temporal/proxy_service/test/monitor_test.py::TestCheckProxyIsLive::test_check_proxy_is_live_success_live` | `us.i.posthog.com:443` |

Docstring literally says _"Live test against us.i.posthog.com"_. It has a sibling `test_check_proxy_is_live_success_mocked` that already covers the logic with mocks. This is exactly what the policy says must live in a tagged external-integration suite — or just be deleted, since the mocked sibling covers it. Owner: proxy/infra (no CODEOWNERS entry).

### B. Accidental egress — a transitive call slipped past the mock (4)

| Test                                                                                                                                                                  | Host                   | Why it leaks                                                                                                                                                                                                                                  |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog/models/test/test_integration_model.py::TestOauthIntegrationModel::test_stripe_integration_from_oauth_response_uses_apps_endpoint_and_basic_auth`             | `api.stripe.com:443`   | `requests.post` is mocked, but the same code path calls `StripeClient(...).accounts.retrieve()` through the Stripe SDK's own HTTP client. Not mocked, exception swallowed by `try/except` → test passes green while calling Stripe every run. |
| `posthog/models/test/test_integration_model.py::TestOauthIntegrationModel::test_stripe_oauth_does_not_persist_is_sandbox`                                             | `api.stripe.com:443`   | Same `integration_from_oauth_response` → StripeClient path.                                                                                                                                                                                   |
| `posthog/api/test/test_integration.py::TestGitHubIntegrationStateValidation::test_create_github_integration_rejects_foreign_installation_id`                          | `api.github.com:443`   | Security/IDOR test. Mocks the install + OAuth-code lookups, but `verify_user_installation_access` calls GitHub's `/user/installations/{id}/repositories` for real — that mock is missing.                                                     |
| `products/mcp_store/backend/test/test_oauth.py::TestIssuerValidation::test_rejects_metadata_with_endpoints_off_issuer_origin_0_token_endpoint_redirected_to_attacker` | `publicsuffix.org:443` | Security test. `_registrable_domain` → `tldextract.extract()` lazily fetches/refreshes the Public Suffix List over the network when its cache is cold. Owner: team-signals.                                                                   |

Two of these four are _security_ tests — an external outage or a behavior change at GitHub/publicsuffix.org could flip them red or, worse, green for the wrong reason.

Fixes: mock `StripeClient`; add the missing GitHub repos-API mock; pin `tldextract` to a bundled offline suffix list (`TLDExtract(suffix_list_urls=(), cache_dir=...)`).

### C. PostHog's own analytics telemetry leaking (2 here — likely many more)

| Test                                                                                                    | Host                   | Path                                                               |
| ------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------ |
| `products/data_warehouse/backend/api/test/test_table.py::TestTable::test_file_upload_creates_new_table` | `us.i.posthog.com:443` | analytics capture                                                  |
| `products/tasks/backend/tests/test_models.py::TestTask::test_create_and_run_internal_defaults_to_false` | `us.i.posthog.com:443` | `Task.save` → `_track_task_created` → `posthoganalytics.capture()` |

Owners: team-managed-warehouse, team-posthog-code.

## Prefilter blind spot (important)

The 76-file candidate set gated on _"imports `requests`/`httpx`/`aiohttp`/`boto3`"_. That excludes every cloud SDK with its own transport — Modal (gRPC), google-cloud, Snowflake, BigQuery, etc. The sensor doesn't care about the client (it works at the socket), so the gate threw away coverage for no detection reason — only to keep the run cheap.

Demonstrated with Modal: 5 of 7 Modal test files never entered the run. Pointing the sensor at them directly surfaced two more leaks the prefilter had hidden:

| Test                                                                                                                                                              | Host                   | Note                                                                                                                     |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `products/tasks/backend/services/tests/test_modal_sandbox.py::TestGetSandboxImageReferenceIntegration::test_resolves_digest_from_ghcr`                            | `ghcr.io:443`          | Resolves a container image digest from GitHub's registry. Class name says `Integration` — a mislocated integration test. |
| `products/tasks/backend/temporal/execute_sandbox/activities/tests/test_reap_orphaned_sandbox.py::TestReapOrphanedSandbox::test_returns_none_when_no_persisted_id` | `us.i.posthog.com:443` | Another analytics-capture leak (category C).                                                                             |

(No `*.modal.com` egress — the Modal SDK calls themselves are mocked.)

Conclusion: don't gate on a client import. The only honest way to get the true count is to run the sensor broadly — register it in the root conftest in record-only mode and collect one full CI shard set, or sweep whole `products/` + `posthog/` test trees in chunks.

## Systemic finding (root cause is an SDK bug, not a missing disable)

`apps.py` **already** sets `posthoganalytics.disabled = True` under TEST. The leak happens anyway because of an SDK bug: `Client.get_flags_decision` is the one flag method **missing the `if self.disabled` guard** that all its siblings have. So `capture(..., send_feature_flags=True)` and `feature_enabled(...)` fire a synchronous live `/flags` request to the analytics host _even when disabled_, before the `_enqueue` disabled check — and `capture()` swallows the error. Verified directly: `settings.TEST=True`, `disabled=True`, and `capture(send_feature_flags=True)` still hit `us.i.posthog.com`.

Fix applied (this branch): `posthog/conftest.py` seals `Client.get_flags_decision` to honor `disabled`, matching the rest of the SDK. This removes the entire synchronous class-C path (capture-with-flags + feature_enabled) suite-wide. The real fix belongs upstream in posthog-python.

Residual: one test (`test_file_upload_creates_new_table`) still egresses once on a background SDK thread (`request.post`, not our `capture` — likely exception autocapture or a batch flush from a non-default client). Background-thread egress can't be walled mid-connect; the session-end enforce gate catches it, and it lands in the recorded baseline to be burned down. Use `NETWORK_AUDIT_FULLSTACK=1` to get full (incl. site-packages) stacks for background-thread cases like this.

## How to reproduce / extend

```bash
# this candidate run
PYTHONPATH=tools/network-audit python -m pytest $(cat candidates.txt) \
  -p pytest_network_audit --network-audit-out=tools/network-audit/out/report.json \
  --timeout=90 --timeout-method=thread --continue-on-collection-errors -q

# firewall mode (fail on any leak) — for CI once the suite is clean
PYTHONPATH=tools/network-audit python -m pytest <paths> -p pytest_network_audit --network-audit-block
```

To find the true full count, enable the sensor globally (register it in the root conftest in record-only mode) for one full CI shard set and collect the merged report.
