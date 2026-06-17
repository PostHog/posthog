# network-audit

A pytest plugin that flags tests making **live outbound connections to third-party
hosts** — the thing the default test suite is not supposed to do. Use it to audit for
violations of the "no outbound network calls in the default suite" policy, or as a
firewall in CI to fail on regressions.

## How it detects

It patches `socket.socket.connect` / `connect_ex` and inspects the destination IP. Local
infra — Postgres, Redis, ClickHouse, Kafka, Temporal, object storage, the egress proxy —
all resolve to loopback or private/link-local addresses. Anything that connects to a
**globally-routable** IP (`ipaddress.is_global`) is, by definition, leaving for the public
internet, so it gets recorded with the triggering test's nodeid and an in-repo stack
snippet. `socket.getaddrinfo` is hooked too, so reports show the hostname when known.

There is no hostname allowlist to maintain — detection is purely by IP class, so it can't
be fooled by a hostname that happens to look internal, and it keeps working as service
names change.

## Usage

The root `conftest.py` loads the plugin automatically when `NETWORK_AUDIT` is set — no
`-p` flag needed (the dir is on `pytest.ini`'s pythonpath). With nothing set it's fully
dormant, so normal local and CI runs are unaffected.

```bash
# record-only: run completes, JSON report written, summary printed
NETWORK_AUDIT=1 NETWORK_AUDIT_OUT=tools/network-audit/out/report.json python -m pytest <paths>

# enforce (the CI gate): fail the whole session if any non-baselined egress was recorded
NETWORK_AUDIT=1 NETWORK_AUDIT_ENFORCE=1 NETWORK_AUDIT_BASELINE=tools/network-audit/baseline.json \
  python -m pytest <paths>
```

You can also point pytest at it explicitly without the env (`-p pytest_network_audit`).

### Modes / options (env var or `--flag`)

- **record** (default) — flag and report, never fail. Use to build/refresh the baseline.
- `--network-audit-block` / `NETWORK_AUDIT=1` only — raise on each _new_ (non-baselined)
  connect, mid-test. Precise line, but can't catch background-thread egress.
- `--network-audit-enforce` / `NETWORK_AUDIT_ENFORCE=1` — at session end, fail the run
  (exit 1) if any non-baselined violation was recorded. Catches background threads too.
  This is the CI gate.
- `--network-audit-baseline PATH` / `NETWORK_AUDIT_BASELINE` — allowlist of known
  offenders to tolerate. JSON: `{"allow": [{"host": "api.x.com", "nodeid": "..."}]}`.
  Omit `nodeid` (or use `"*"`) to allow any test to reach that host.
- `--network-audit-out PATH` / `NETWORK_AUDIT_OUT` — JSON report path
  (default `.network-audit.json`).

### Regenerating the baseline from a report

```bash
python - <<'PY'
import json
ev = json.load(open("tools/network-audit/out/report.json"))["events"]
seen = {(e["nodeid"], e["host"] or e["ip"]) for e in ev}
allow = [{"nodeid": n, "host": h} for n, h in sorted(seen)]
json.dump({"allow": allow}, open("tools/network-audit/baseline.json", "w"), indent=2)
PY
```

## Caveats

- Connections during collection/import (module-level) are attributed to
  `<no active test>` — still worth investigating.
- A test that is mocked at runtime never connects, so it won't be flagged. That's the
  point: this measures real egress, not static URL presence (which is noisy — most tests
  carry real-looking URLs purely as fixture strings).
- It sees real sockets only. A test that stubs `requests`/`httpx`/`aiohttp` above the
  socket layer is invisible to it (and harmless — no socket opens).
