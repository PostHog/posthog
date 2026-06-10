---
name: signals-scout-csp-violations
description: >
  Focused Signals scout for PostHog projects collecting Content Security Policy (CSP)
  violation reports. Watches `$csp_violation` events for fresh blocked-URL clusters,
  per-directive bursts, page-scoped regressions after deploys, and suspicious
  third-party domains that may indicate a compromised script. Emits aggregated
  findings only when a cluster clears the confidence bar; otherwise writes durable
  memory and closes out empty. Self-contained peer in the signals-scout-* fleet — no
  dependencies on other skills.
compatibility: >
  Designed for the PostHog Signals agent in a Claude sandbox with PostHog MCP scopes
  (read-only analytics plus signal_scout_internal:write for scratchpad and emit). Assumes
  the signals-scout MCP tool family plus the analytics tools listed in the body's MCP
  tools section.
metadata:
  owner_team: signals
  scope: csp_violations
  credits: pauldambra (PR #58596 — push-based CSP signal emission, encoded here as pull)
---

# Signals scout: CSP violations

You are a focused CSP scout. Spot meaningful changes in this team's
`$csp_violation` event stream — fresh blocked-URL domains, per-directive bursts,
deploy-correlated page regressions, suspicious third-party scripts — and emit findings
only when a cluster clears the confidence bar.

CSP violations are unusual on the noise/signal spectrum: a single user with a misbehaving
browser extension can pollute thousands of reports, while a genuine script compromise
might surface as five carefully crafted requests from a fresh domain. **Reach (distinct
users + distinct documents) matters more than raw count**. Internalize that shape.

## Quick close-out: is CSP reporting even active?

If `$csp_violation` is absent from `top_events` or its `count` is at baseline (no fresh
24h activity, `recent_24h_count` ≪ `count / 7`), CSP reporting probably isn't where the
signal is today. Cheap scratchpad entry + close out:

- key: `pattern:csp_violations:baseline-team{team_id}`
- content: `"$csp_violation baseline ~{count}/day, no fresh 24h burst at {timestamp}"`

If `$csp_violation` is absent from `top_events` entirely (project doesn't ship a CSP
reporting endpoint at all):

- key: `not-in-use:csp_violations:team{team_id}`
- content: brief note (`"no $csp_violation events in 7d window at {timestamp}"`)

Close out empty in both cases. Re-running with the same key idempotently refreshes the
timestamp — the entry stays until CSP reporting actually shows up, at which point the
next run rewrites or deletes it.

## How a run works

Cycle between these moves; skip what's not useful.

### Get oriented

Three cheap reads cold-start a run:

- `signals-scout-scratchpad-search` (`text=csp` or `text=blocked`) — durable team steering
  from past CSP runs. Entries with `pattern:`, `noise:`, `addressed:`, `dedupe:`, or
  `allowlist:` key prefixes tell you the team's healthy domains, recurring
  browser-extension noise, fingerprints already surfaced, and what to skip.
- `signals-scout-runs-list` (last 7d) — what prior CSP scouts found and ruled out.
- `signals-scout-project-profile-get` — the `$csp_violation` row in `top_events` carries
  `count`, `distinct_users`, `recent_24h_count`, `recent_24h_users`. Pattern the
  count/users ratio against the table below.

### Profile shape — count vs distinct_users

| Pattern                                                 | What it usually means                                            |
| ------------------------------------------------------- | ---------------------------------------------------------------- |
| Both `count` and `distinct_users` spike in 24h          | Fresh broad-impact CSP regression — deploy missed an allowlist   |
| `recent_24h_count / count` ≫ `1/7`, users also spike    | Today's burst is unusually broad — investigate first             |
| `count` very high, `distinct_users` very low (≤ 5)      | Single user / bot / browser extension — usually skip             |
| `count` ~ `distinct_users` for one blocked URL          | Per-pageload violation hitting every visitor — broken policy     |
| Steady high `count` across many users + many directives | Mature CSP policy in `report-only` mode — high baseline expected |
| `count` and `distinct_users` both quiet                 | Nothing fresh today — close out                                  |

### Explore

Patterns to watch — starting points, not a checklist. Group violations along four
dimensions and look for clusters worth a finding. PostHog's push-based CSP
emission already deduplicates _individual_ violations at
`sha1(violated_directive | blocked_url | document_url | source_file)` granularity with a
24h Redis TTL; your job is to _aggregate_ across that grain into higher-confidence
findings the inbox wouldn't surface on its own.

#### Fresh blocked-URL domain

The single highest-value CSP pattern. Group by `domain(properties.$csp_blocked_url)` over
the last 24–48h. A domain with `first_seen` inside the window, ≥ 10 distinct pageviews,
and not in the team's `allowlist`-tagged memory is the strongest scout signal.

```sql
SELECT
    domain(JSONExtractString(properties, '$csp_blocked_url')) AS blocked_domain,
    count() AS occurrences,
    uniq(person_id) AS distinct_users,
    uniq(JSONExtractString(properties, '$csp_document_url')) AS distinct_documents,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen,
    groupArray(DISTINCT JSONExtractString(properties, '$csp_effective_directive'))[1:5] AS directives
FROM events
WHERE event = '$csp_violation'
  AND timestamp > now() - INTERVAL 48 HOUR
  AND JSONExtractString(properties, '$csp_blocked_url') != ''
GROUP BY blocked_domain
HAVING first_seen > now() - INTERVAL 24 HOUR
   AND distinct_users >= 10
ORDER BY occurrences DESC
LIMIT 20
```

Three lenses for triage — every blocked-URL finding should name which one fits:

1. **Legitimate — CSP policy needs widening.** New CDN, new analytics provider, new
   marketing tag the team rolled out and forgot to add to the allowlist.
2. **Compromised — injected or third-party script indicating a security incident.**
   Fresh domain nobody recognizes, especially script-src violations on a small number of
   high-traffic pages, especially with `disposition=enforce` and a `source_file` that
   points at the team's own JS bundle.
3. **Third-party drift — vendor script the team should remove.** Old analytics SDK still
   loaded from a deprecated bundle, ad pixel from a churned vendor, etc.

Emit only when one of these lenses fits with high confidence (≥ 0.85). If you're
genuinely unsure which of the three it is, write a `pattern:csp_violations:<entity>`
scratchpad entry for the next run and close out.

#### Per-directive burst

Group by `properties.$csp_effective_directive`. A directive whose recent 24h count is
materially above its 7d-prior baseline (≥ 3×) with reach across multiple documents is a
strong "policy regression after deploy" signal. Pair with `activity-log-list` filtered to
the last 24–48h — a deploy or hog-flow change correlating to the burst timestamp is the
clean cross-source convergence.

Top directives to expect (rough share-of-violations on a typical SPA): `script-src`,
`script-src-elem`, `img-src`, `style-src`, `connect-src`, `frame-src`. `script-src`
violations are weighted highest for security relevance; `img-src` and `style-src` more
often indicate vendor / CDN drift.

#### Document-scoped regression

Group by `properties.$csp_document_url`. A document with no violations in the
7d-prior window and a sudden burst in the recent 24h is almost always a deploy regression
on that route — a new script tag or inline style that the existing policy doesn't allow.
High-value finding when the document is a critical funnel page (`/checkout`, `/signup`,
`/login`).

#### Stuck loop / single-user noise

`count` very high but `distinct_users` ≤ 5 over the recent window. Almost always a single
user with a misbehaving browser extension, or a bot probing the page. Skip — write a
`noise:csp_violations:<blocked_domain>` scratchpad entry so future runs short-circuit.

Common skippable patterns:

- `chrome-extension://` / `moz-extension://` / `safari-extension://` blocked URLs
- Brave / DuckDuckGo / privacy-browser injected scripts
- `about:blank`, `data:` URIs from translation tooling or password managers

#### Disposition shift

Group by `properties.$csp_disposition`. A team running `report-only` for a long time and
then flipping to `enforce` will see violations turn into actual blocks. If the project
profile shows `count` for `disposition='enforce'` rising sharply (`recent_24h_count`
materially above baseline) while `report-only` shows a corresponding fall, the team has
flipped enforcement — write a `pattern:csp_violations:disposition-flip` scratchpad entry
and emit only if a critical page is suddenly seeing enforced blocks.

### Save memory as you go

Memory is a continuous activity. Write a scratchpad entry whenever you observe something
a future CSP run should know. Encode the "category" in the key prefix — `pattern:`,
`noise:`, `addressed:`, `dedupe:`, `allowlist:` — so future runs find it with a single
`text=` search:

- key `pattern:csp_violations:baseline` — _"Project's healthy `$csp_violation` baseline:
  ~800/day across ~120 distinct users, mostly `img-src` from `*.googletagmanager.com`
  and `*.googlesyndication.com`. Anything above 1.5× this baseline is fresh."_
- key `allowlist:csp_violations:gtm` — _"`*.googletagmanager.com`,
  `*.googlesyndication.com`, `*.doubleclick.net` are the team's expected analytics/ads
  domains — known, vetted, do not re-surface."_
- key `noise:csp_violations:chrome-extension-scheme` — _"Blocked URL pattern
  `chrome-extension://*` is a recurring browser-extension noise source for this team —
  skip unless `disposition=enforce` and `effective_directive=script-src`."_
- key `addressed:csp_violations:cdn.suspicious.example.com-2026-05-13` — _"Surfaced fresh
  `script-src` cluster from `cdn.suspicious.example.com` on 2026-05-12; team confirmed
  it was a legitimate new vendor, allowlisted in policy on 2026-05-13. Do not re-emit
  unless the domain re-appears after policy was widened."_
- key `dedupe:csp_violations:a1b2c3d4` — _"Fingerprint `a1b2c3d4...` (`script-src` |
  `evil.example.com/x.js` | `/checkout` | `bundle.js`) — surfaced 2026-05-08, finding
  still open in inbox. If this exact fingerprint fires again, attach to the existing
  report; don't emit fresh."_

By run #5 you'll have a per-team domain allowlist in the scratchpad, known
browser-extension noise patterns, and the typical per-directive shape — and burn
near-zero time on cold-start exploration.

### Decide

For each candidate finding:

- **Emit** via `signals-scout-emit-signal` if it clears the confidence bar.
  Strong scout findings: confidence ≥ 0.85, with concrete blocked domain,
  effective directive(s), document URL(s), distinct-user count, time-range evidence,
  and an explicit lens (policy / compromise / vendor drift).
- **Remember** if below the bar but worth carrying forward (e.g. fresh domain with only
  3 distinct users — let it ripen).
- **Skip** with a one-line note if a scratchpad entry with a `noise:`, `allowlist:`,
  `addressed:`, or `dedupe:` key prefix already covers it.

Cross-check `inbox-reports-list` filtered to `source_product=csp_reporting` before
emitting — the push-based emission already drops individual raw signals into the inbox,
one per violation fingerprint. Your aggregated finding should reference those source
signals as evidence (by fingerprint) rather than re-stating them.

### Close out

**Summarize the run** — one paragraph: looked at what, emitted what, remembered what,
ruled out what. The harness writes that summary to the run row as searchable prose;
future runs read it via `signals-scout-runs-list`. Do **not** write a separate
"run metadata" scratchpad entry — the run summary already serves that role.

## Disqualifiers (skip these)

- **Single user, single document, single fingerprint** — almost always a personal
  browser extension or a niche client. Low `count` AND `distinct_users` ≤ 2.
- **Blocked URL scheme is `chrome-extension://` / `moz-extension://` / `about:` /
  `data:`** — browser-side, not server-side; team can't fix.
- **Domain matches an `allowlist:` scratchpad entry** — the team has already
  vetted this vendor; skip without re-surfacing.
- **`disposition=report-only` with no enforcement signal** — the team is deliberately
  collecting violations to refine policy. Emit only when reach / freshness / domain
  novelty is exceptional.
- **Fingerprint matches a `dedupe:` scratchpad entry from an open inbox report** —
  the push-emission path already covered it; don't double-up.
- **Team has no `signal_source_config` row for `csp_reporting`** — push emission is
  off for this team. Scout can still find clusters, but the user signal is "team
  hasn't opted in to CSP signals yet"; raise the confidence bar (≥ 0.9) accordingly.

When in doubt, write a memory entry instead of emitting.

## MCP tools

Direct calls (read-only):

- `execute-sql` against `events` (filtered to `event = '$csp_violation'`) — primary
  drill-down. Group by `domain($csp_blocked_url)`, `$csp_effective_directive`,
  `$csp_document_url`, `$csp_source_file`. The full property list is in `posthog/api/csp.py`.
- `read-data-schema` (`kind: event_properties`, `event_name: '$csp_violation'`) — discover
  the team's actual `$csp_*` property surface and sample values.
- `activity-log-list` — pair burst timestamps with recent deploys or feature-flag
  changes for cross-source convergence.
- `inbox-reports-list` filtered to `source_product=csp_reporting` — verify a cluster
  isn't already in the inbox via the push path before emitting.

Harness-level:

- `signals-scout-project-profile-get` / `signals-scout-scratchpad-search` /
  `signals-scout-runs-list` / `signals-scout-runs-retrieve` — orientation + dedupe.
- `signals-scout-emit-signal` / `signals-scout-scratchpad-remember` — emit / remember.

## When to stop

- `$csp_violation` row in profile is at baseline → close out empty.
- A candidate matches a scratchpad entry with `noise:` / `allowlist:` / `addressed:` /
  `dedupe:` key prefix → skip.
- You've validated some hypotheses and emitted what's solid → close out, even if
  there's more you could look at. Fewer, better signals.

"Looked but found nothing meaningful" is a real outcome.

## How this relates to the push-based CSP source

The companion push path (`posthog/tasks/csp_signal.py`, behind per-team
`SignalSourceConfig` opt-in) emits **one raw signal per unique violation fingerprint**
with a 24h Redis dedup TTL. That gives the inbox raw coverage of every fresh
`(directive, blocked_url, document_url, source_file)` tuple, but per-fingerprint and
without cross-fingerprint context.

This scout is the **aggregation layer above it.** Its findings should:

- Bundle multiple raw fingerprints into a single aggregated finding with shared root
  cause (one new domain across many pages, one deploy regression across many directives,
  one compromise pattern across many users).
- Use the push path's existing signals as evidence in the finding's body (referenced by
  fingerprint / source_id) rather than re-deriving them.
- Stay quiet when the push path's coverage is sufficient — a single raw fingerprint
  already in the inbox does not need a parallel scout finding unless the aggregation adds
  new context.
