# ReviewHog incident golden set: demo links

One block per incident: the PR that caused it, the PR that fixed it, the resurrected copy ReviewHog reviewed, and the exact ReviewHog comment. Then the bug, what the fix did, what ReviewHog said and suggested, and how the two relate. Published verdicts: hit = same root cause on the same code path, partial = the area, symptom or precondition without the mechanism, miss = nothing relevant. Private-repo rows (charts, posthog-cloud-infra) keep links and verdict only. Verdicts are LLM-judged; see FINAL_REPORT.md in this directory for the method, the scores and the caveats. Bug and fix descriptions use only what the linked public PRs show.

Published: 13 hits, 9 partials, 11 misses (n = 33).

## Hits (13)

### INC-392 · Critical · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/32065) · [Fix PR](https://github.com/PostHog/posthog/pull/32173) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93659) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93659#discussion_r3917671776)** (must_fix)

- **Bug:** Unflagged progress endpoint polled ClickHouse's cluster-wide system.processes once a second for up to ten seconds on every blocking query. The frontend opened that stream with no teardown.
- **Fix:** #32173 reverted the change. It removed the progress endpoint and the frontend stream opener, and restored the earlier flag-gated SSE query endpoint. No re-land is recorded.
- **ReviewHog said:** Every blocking query opens a progress stream after 500 ms with no cleanup. Fast queries have already finished, so the backend runs about ten cluster-wide ClickHouse probes per stream.
- **ReviewHog suggested:** Give the progress stream its own AbortController. Clear the timer and abort it when the query settles. Also forward the caller's abort.
- **How they relate:** Hit. ReviewHog named the per-second cluster-wide probes at must_fix. Its abort fix only stops streams for fast queries, since the server never cancels a running stream. Slower queries would still cost ten probes each, so the suggestion removes most of the probes rather than all of them.

### INC-193 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/22181) · [Fix PR](https://github.com/PostHog/posthog/pull/22187) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93671) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93671#discussion_r3917586671)** (must_fix)

- **Bug:** #22181 narrowed the dashboard cached-result guard in propsChanged, so result-less tiles started live loads; each re-render aborted the last one, sending DELETE /query for the aborted request.
- **Fix:** #22187 reverted the change. It restored the old guard that blocks any dashboard tile with cached results and put the one-at-a-time refresh loop back in place of runWithLimit(2). No re-land is named.
- **ReviewHog said:** A result-less dashboard tile starts a load on every render; the loading re-render fires propsChanged again and aborts the first request, and failures repeat this without limit.
- **ReviewHog suggested:** Gate fallback loads with !values.dataLoading, remember which query version already used the fallback, and retry only after an explicit refresh or query change.
- **How they relate:** Same root cause on the same lines. ReviewHog traced the loosened guard to the re-render, abort, and DELETE /query cycle; its loading gate would have stopped that cycle. The fix removed it by reverting the guard instead.

### INC-390 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/31685) · [Fix PR](https://github.com/PostHog/posthog/pull/32012) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93660) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93660#discussion_r3917682405)** (should_fix)

- **Bug:** A submission-deduplication subquery over the events table, with no team or time bound, was embedded in every survey-results query, including one per question.
- **Fix:** #32012 is a plain revert of the surveys change. The re-land #32034 gated the deduplication behind a feature flag and collapsed the two-scan UNION into one argMax scan.
- **ReviewHog said:** Every question loader embeds the same deduplication scan, so an N-question survey runs N extra scans plus stats and table scans, even when partial responses are off.
- **ReviewHog suggested:** Only add this filter when the survey's partial-responses setting is on. For those surveys, deduplicate once in a backend query and return all question aggregates.
- **How they relate:** Same mechanism, near-same remedy. ReviewHog wanted the filter gated on the survey's partial-responses setting, off by default. The re-land gated it on a feature flag instead. Either gate removes the scan from nearly every survey.

### INC-487 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/36448) · [Fix PR](https://github.com/PostHog/posthog/pull/36573) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93658) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93658#discussion_r3917575263)** (must_fix)

- **Bug:** A change first forwarded the Events exclusion list to the event definitions API. Existing pickers pass a null placeholder, so the backend interpolated ARRAY[None] into raw SQL and returned 500.
- **Fix:** #36573 re-landed the reverted change and filters every forwarded exclusion list down to strings with .filter(isString). It also omits the query param when the list is empty. The backend SQL branch came back unchanged.
- **ReviewHog said:** Existing callers use Events: [null] to hide the local All events option. Forwarded to the API it becomes ARRAY[None] and returns 500. Cohort, replay trigger and LemonEventName pickers stop loading.
- **ReviewHog suggested:** Keep null local. Send only strings to the remote group, filtered by typeof value === 'string'. Also reject non-strings at the API. Add a test.
- **How they relate:** Direct hit. ReviewHog flagged the line #36573 edited and asked for a string-only filter on the forwarded list. That is what the fix did, so applying the suggestion would have stripped the null before the request and avoided the 500.

### INC-717 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/48173) · [Fix PR](https://github.com/PostHog/posthog/pull/48361) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93643) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93643#discussion_r3917179432)** (should_fix)

- **Bug:** New taxonomic filter groups looked up event and person property values with no event filter and no minimum search length. Every picker open and keystroke fired unfiltered ClickHouse value scans.
- **Fix:** #48361 reverted the change. The re-land #48371 added a minimum search length before querying, sent the event filter with the queries, and put each query type behind its own flag.
- **ReviewHog said:** The new groups load on mount and after each search. Each selector starts three more queries, including a person query that can scan 100,000 rows. This adds backend load.
- **ReviewHog suggested:** Load a remote group only when its tab becomes active. For Suggested filters, wait for a non-empty debounced query. Apply to all affected selectors.
- **How they relate:** Same mechanism, different remedy. Loading groups only on active tabs and only after a typed query, as ReviewHog asked, would have stopped the unfiltered ClickHouse value scans. The re-land used a minimum search length, plus event filter and flags.

### INC-834 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/57782) · [Fix PR](https://github.com/PostHog/posthog/pull/57817) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93638) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93638#discussion_r3917195753)** (must_fix)

- **Bug:** Switching the shared-dashboard auto-refresh hook to useActions mounted the dashboard logic without the serialized dashboard. The logic fetched the dashboard unauthenticated, got a 401, and blanked shared pages.
- **Fix:** #57817 reverted the whole bundle-split PR #57782. The re-land, #57853, kept useActions but seeded the logic with the serialized dashboard, so the logic used the cached data on mount instead of fetching.
- **ReviewHog said:** useActions mounts the dashboard logic during render, before the dashboard component binds it with the dashboard data. The first mount ignores the serialized dashboard and issues a new request.
- **ReviewHog suggested:** Go back to logic.actions, which does not mount early, or bind one logic seeded with the dashboard data around both components.
- **How they relate:** Same line, same mechanism. The revert matches its first suggestion, restoring logic.actions. The re-land matches its second, seeding the logic with the dashboard. Either removes the unauthenticated fetch. ReviewHog only underrated impact, expecting slowness rather than a 401.

### INC-938 · Major · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/63600) · [Fix PR](https://github.com/PostHog/posthog/pull/66932) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93636) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93636#discussion_r3917310150)** (must_fix)

- **Bug:** The managed-view sync took a session-scoped pg_advisory_lock on the PgBouncer transaction-pooled connection. The unlock could hit a different backend, stranding the lock. Later callers waited forever and pinned pool connections.
- **Fix:** #66932 deleted the session advisory lock and its finally-block unlock around the DAG node/edge sync. It kept only the transaction-scoped pg_advisory_xact_lock, accepting a race on DAG placement for now.
- **ReviewHog said:** Session advisory lock on the pooled connection is unsafe. Under transaction pooling the unlock can land on another server session. The lock stays held; waiters block forever, pinning pool connections.
- **ReviewHog suggested:** Resolve dependencies first. Hold a transaction-scoped lock, with a finite timeout, only for the short graph mutation. Otherwise use an expiring row lease.
- **How they relate:** Same lines, same root cause. ReviewHog named the stranded session lock under transaction pooling and asked for a transaction-scoped lock instead. The fix dropped that session lock, so acting on the finding would have prevented the pool exhaustion.

### INC-239 · Minor · ✅ hit · private repo

[Introducing PR](https://github.com/PostHog/charts/pull/1810) · [Fix PR](https://github.com/PostHog/charts/pull/1811) · [Resurrected PR](https://github.com/PostHog/charts/pull/15075) · **[ReviewHog comment](https://github.com/PostHog/charts/pull/15075#discussion_r3917479467)** (should_fix)

- Private repo: details withheld. Verdict hit: the finding sits on the incident's lines and names its mechanism.

### INC-694 · Minor · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/45814) · [Fix PR](https://github.com/PostHog/posthog/pull/46233) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93645) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93645#discussion_r3917023034)** (must_fix)

- **Bug:** Google Ads incremental filter on segments.date changed from >= to >. The cursor is the open current day, so the next sync excludes the rest of that day.
- **Fix:** #46233 is a straight revert of #45814: one line in get_rows goes from > back to >=, so every sync reads the watermark day again.
- **ReviewHog said:** The open day gets stored as the cursor. The new > filter then excludes all later rows and metric updates for that date, so daily partitions stay partial.
- **ReviewHog suggested:** Keep > for closed dates but exclude the open day: query through the last completed day in the customer time zone, and add a test.
- **How they relate:** Same line, same root cause: > plus a date cursor drops the rest of the open day. ReviewHog would stop querying the open day; the fix reverted to >=. Both prevent the incident.

### INC-702 · Minor · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/44198) · [Fix PR](https://github.com/PostHog/posthog/pull/46696) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93644) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93644#discussion_r3917457005)** (must_fix)

- **Bug:** #44198 made the shared key finder in posthog/auth.py raise for phs\_ tokens. The rate throttle re-calls that finder after auth, so valid legacy secret tokens on local evaluation got 401.
- **Fix:** #46696 is a full revert of #44198, so the phs\_ raise left with the feature. The author's follow-up #46798 dropped that raise and let the auth chain continue, but it closed unmerged.
- **ReviewHog said:** With rate limiting on, the throttle re-parses the header after project-key auth and the new phs\_ branch raises. A valid header request then fails on local evaluation and remote config.
- **ReviewHog suggested:** Have the throttle read the authenticator that already succeeded instead of re-parsing the header, move the phs\_ check into PersonalAPIKeyAuthentication.authenticate, and add rate-limit-enabled tests.
- **How they relate:** Same root cause, same lines. ReviewHog said the phs_raise in the shared key finder 401s valid legacy tokens on local_evaluation and asked to move it out. That removes the raise the throttle hits, as the revert and follow-up did.

### INC-711 · Minor · ✅ hit · private repo

[Introducing PR](https://github.com/PostHog/posthog-cloud-infra/pull/6645) · [Fix PR](https://github.com/PostHog/posthog-cloud-infra/pull/6652) · [Resurrected PR](https://github.com/PostHog/posthog-cloud-infra/pull/10210) · **[ReviewHog comment](https://github.com/PostHog/posthog-cloud-infra/pull/10210#discussion_r3917021528)** (must_fix)

- Private repo: details withheld. Verdict hit: the finding sits on the incident's lines and names its mechanism.

### INC-815 · Minor · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/55662) · [Fix PR](https://github.com/PostHog/posthog/pull/56117) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93641) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93641#discussion_r3917158182)** (must_fix)

- **Bug:** The process-task workflow added a PR-context activity before the existing CI follow-up step with no Temporal patch gate, so in-flight runs hit replay errors and stopped progressing.
- **Fix:** #56117 wrapped the branch in workflow.patched("tasks-ci-follow-up-pr-context"). Unpatched histories take a legacy replay-only dispatch that keeps the old command order; patched runs do the new PR-context check first.
- **ReviewHog said:** The change inserts get_pr_context before the existing follow-up command. Runs started before deploy replay a different first command, causing Temporal nondeterminism, and the tasks worker has no version routing.
- **ReviewHog suggested:** Guard the change with workflow.patched. Keep the old command sequence on the legacy branch, run the PR check only when patched, deprecate the patch later.
- **How they relate:** Same change. ReviewHog asked for a workflow.patched gate that keeps the legacy command sequence for old histories, and that is exactly what #56117 shipped on the same lines. Applying it before merge would have kept in-flight runs replaying cleanly.

### INC-931 · Minor · ✅ hit

[Introducing PR](https://github.com/PostHog/posthog/pull/65999) · [Fix PR](https://github.com/PostHog/posthog/pull/66215) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93637) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93637#discussion_r3917401046)** (must_fix)

- **Bug:** Once the open timer fired, lazy tooltip mounting swapped in a different element type at the trigger position. React replaced the trigger DOM node under every LemonButton, dropping focus and child state on every tooltip-bearing control.
- **Fix:** #66215 reverted #65999. It removed the lazy prop and open timer, folded the mounted-state component back into the single Tooltip component, and deleted the lazy-mount test. No re-land is named.
- **ReviewHog said:** When the open timer fires, Tooltip renders a different element type at the same tree position. React deletes the trigger DOM node and recreates it, dropping focus and child state.
- **ReviewHog suggested:** Keep the same trigger element and component instance when focus opens the tooltip. If that is not possible, disable lazy mounting for focusable controls.
- **How they relate:** Same code path and mechanism. ReviewHog named the branch swap that replaces the trigger DOM node and asked to keep one element or drop lazy mounting. Either removes the swap under every tooltip-bearing control, which is what the revert did.

## Partials (9)

### INC-120 · Major · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/17466) · [Fix PR](https://github.com/PostHog/posthog/pull/19110) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93676) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93676#discussion_r3917511243)** (should_fix)

- **Bug:** A ClickHouse migration added a SELECT \* projection on sharded_events and materialized it for the live partition, cluster-wide, at deploy time. The rewrite caused an outage at deploy time.
- **Fix:** #19110 deleted the migration file 0049_add_inserted_at_projection.py outright. The projection had already been dropped by hand in production. The PR body says it would be reworked and added back later.
- **ReviewHog said:** MATERIALIZE PROJECTION queues a full-month mutation on every shard during deploy. The migration records success at once, with no progress check, failure check, or retry.
- **ReviewHog suggested:** Move the materialization to an async migration. Run one partition or shard at a time, poll system.mutations, apply background resource limits.
- **How they relate:** Partial match. ReviewHog flagged the deploy-time, cluster-wide rewrite and asked for a throttled async rollout, but never said it would overload the cluster at deploy time. The fix deleted the migration. A throttled rollout still runs the full rewrite, so prevention is uncertain.

### INC-218 · Major · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/23808) · [Fix PR](https://github.com/PostHog/posthog/pull/23977) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93670) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93670#discussion_r3917625247)** (should_fix)

- **Bug:** dataNodeLogic resumed any incomplete cached query on every prop change. Each run aborted the previous one, sent a cancel, and re-enqueued. The revert PR says this might have contributed to a ZooKeeper incident.
- **Fix:** #23977 was a bare revert. The re-land #23978 added a hasQueryChanged gate so the resume branch fires only when the query changes, and switched dashboard polling to cache-only reads.
- **ReviewHog said:** loadData copies the shared cache-key query id. An abort from a filter change or unmount then sends DELETE for that id, killing a refresh other viewers are polling.
- **ReviewHog suggested:** Track whether the data node created the query id. Stop only the local poll for a resumed status. Cancel only ids it created.
- **How they relate:** Partial. Same cancel path: ReviewHog flagged a one-off abort deleting a shared query. It missed that the branch re-fired on every prop change. Its ownership fix would have stopped the shared-query cancellations but not the resubmit loop.

### INC-242 · Major · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/25129) · [Fix PR](https://github.com/PostHog/posthog/pull/25199) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93668) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93668#discussion_r3917520807)** (must_fix)

- **Bug:** Two beat entries passed a five-field cron string to crontab() as the minute argument. The night string raised during setup, Celery swallowed it, and every later periodic task went unregistered.
- **Fix:** #25199 swapped both crontab calls to get_crontab, a two-line change. Follow-up #25210 wrapped the setup in try/except with a PagerDuty alert on cloud and added a test that runs the setup.
- **ReviewHog said:** Both entries share one name, so the night entry silently overwrites the day one. A validator bullet adds that the day call passes a five-field cron string as minute, not get_crontab.
- **ReviewHog suggested:** Use distinct names for the day and night entries. Add a scheduler test that checks both entries and their arguments.
- **How they relate:** Partial. Same lines, wrong headline. ReviewHog led with a name collision; only a validator aside named the cron string misuse and get_crontab, the exact fix in #25199. A reader acting on the headline would rename the entries and keep the bad crontab call. The suggested scheduler test might still have surfaced the night ValueError before deploy.

### INC-814 · Major · 🟡 partial · private repo

[Introducing PR](https://github.com/PostHog/charts/pull/10224) · [Fix PR](https://github.com/PostHog/charts/pull/10468) · [Resurrected PR](https://github.com/PostHog/charts/pull/15072) · **[ReviewHog comment](https://github.com/PostHog/charts/pull/15072#discussion_r3917109965)** (must_fix)

- Private repo: details withheld. Verdict partial: the review named the incident's area without the mechanism.

### INC-990 · Major · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/83059) · [Fix PR](https://github.com/PostHog/posthog/pull/84891) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93633) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93633#discussion_r3917202264)** (consider)

- **Bug:** #83059 made the stored from.email load-bearing: resolveFromEmailAddress threw on any address off the sender's verified domain, so steps still carrying an old placeholder address failed every send.
- **Fix:** #84891 made resolveFromEmailAddress fall back to the integration's own sender for an invalid or off-domain override, with a warn log, instead of throwing. Not a revert.
- **ReviewHog said:** Switching the sender integration keeps the custom email. If the new integration uses another domain, the send-time domain check throws and every invocation of that step fails.
- **ReviewHog suggested:** Clear the custom email when the integration changes in EmailTemplater.tsx. Keep the name. Add a component test that switches between different-domain integrations.
- **How they relate:** Same throw site and same whole-step failure, but ReviewHog blamed an integration switch and proposed clearing the field in the editor. That leaves old stored placeholders untouched, so it would not have prevented the incident. The fix changed the runtime.

### INC-154 · Minor · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/19938) · [Fix PR](https://github.com/PostHog/posthog/pull/20232) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93673) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93673#discussion_r3917558493)** (must_fix)

- **Bug:** Added a 3-day grace window that moved over-quota team tokens into a new Redis retention set. Capture still read only the old limiter set, so capture never saw the moved tokens.
- **Fix:** #20232 reverted the change the same day. It restored the single limiter set and the old org_quota_limited_until logic. No re-land is named; a later #23200 fixed the mangled Enum cache key.
- **ReviewHog said:** Billing refreshes drop retained_period_end from organization usage, so each sync grants a new 3-day grace and keeps tokens in the retention set. An over-quota org is never quota limited.
- **ReviewHog suggested:** Add retained_period_end to the usage schema and keep it when a billing response is merged in. Add a test for refreshes during grace.
- **How they relate:** Same code path and symptom: tokens land in a retention set capture never reads. But it blames billing merges, not the first run after deploy, when no org had a deadline. Keeping the field across merges would not stop that.

### INC-496 · Minor · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/36834) · [Fix PR](https://github.com/PostHog/posthog/pull/37167) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93656) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93656#pullrequestreview-5093960748)** (must_fix)

- **Bug:** Session auth began calling enforce_two_factor with no SSO exemption. SSO logins never mark a session verified, so SSO users in orgs enforcing 2FA got 403s and a forced 2FA prompt.
- **Fix:** #37167 was a full revert of #36834. The re-land, #37176, made enforce_two_factor skip SSO-authenticated sessions and SSO-enforced domains, and whitelisted the SAML and social login paths.
- **ReviewHog said:** two_factor_validate always reads a session key that only setup writes, so a user with an existing TOTP device cannot verify and gets a 500 instead.
- **ReviewHog suggested:** Add a branch that verifies the existing TOTP device or a backup code, reuse TwoFactorViewSet throttling, and set the session flag on success.
- **How they relate:** Partial. The validator note names the precondition and symptom: SSO login leaves the verified flag unset, so SSO users hit the non-closable modal. But it blamed the verify endpoint, and its suggested fix would still enforce 2FA on SSO sessions.

### INC-563 · Minor · 🟡 partial · private repo

[Introducing PR](https://github.com/PostHog/posthog-cloud-infra/pull/5476) · [Fix PR](https://github.com/PostHog/posthog-cloud-infra/pull/5491) · [Resurrected PR](https://github.com/PostHog/posthog-cloud-infra/pull/10211) · **[ReviewHog comment](https://github.com/PostHog/posthog-cloud-infra/pull/10211#discussion_r3917421646)** (should_fix)

- Private repo: details withheld. Verdict partial: the review named the incident's area without the mechanism.

### INC-987 · Minor · 🟡 partial

[Introducing PR](https://github.com/PostHog/posthog/pull/72913) · [Fix PR](https://github.com/PostHog/posthog/pull/83804) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93635) · **[ReviewHog comment](https://github.com/PostHog/posthog/pull/93635#discussion_r3917341048)** (must_fix)

- **Bug:** #72913 encrypted secret inputs and masked them on read without a backfill. Re-saving an old flow found nothing to recover and dropped the secret, so the webhook step lost its stored credential.
- **Fix:** #83804 reads legacy plaintext from the stored actions as the recovery base, fails validation on a masked marker with nothing stored. It recovers or drops markers on lenient draft saves and adds a backfill command.
- **ReviewHog said:** Lenient draft saves keep raw inputs when a sibling input is invalid, so the {"secret": true} marker gets encrypted and stored, replacing a valid credential.
- **ReviewHog suggested:** Recover secret markers before lenient validation can fail, or have partition_flow_secrets replace markers from the existing secret map. Add a regression test.
- **How they relate:** Same wipe path, different trigger. ReviewHog blamed lenient draft saves with an invalid sibling and wanted recovery from the existing secret map. Legacy rows have an empty map, so that would not have helped; the fix reads their plaintext too.

## Misses (11)

### INC-488 · Critical · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/26822) · [Fix PR](https://github.com/PostHog/posthog/pull/36565) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93657) · [Review summary](https://github.com/PostHog/posthog/pull/93657#issuecomment-5514326293)

- **Bug:** PR #26822 registered raw_query_log as a directly queryable HogQL table over system.query_log. The registration carried no scoping of its own.
- **Fix:** #36565 deleted both tables. It removed query_log and raw_query_log from the HogQL database schema, dropped the printer carve-out, and deleted the query_log.py module and its tests.
- **ReviewHog posted instead:** Five findings on the lazy query_log view: unbounded scans, impersonated staff rows, wrong start time, float type, blank query text. Nothing on the raw_query_log registration itself.
- **How they relate:** Miss. ReviewHog's closest finding wanted an impersonation tag on the lazy view, and read its mismatched key filter as returning nothing. That change leaves the raw_query_log registration untouched, so the incident still happens.

### INC-775 · Critical · ❌ miss · private repo

[Introducing PR](https://github.com/PostHog/charts/pull/9360) · [Fix PR](https://github.com/PostHog/charts/pull/9396) · [Resurrected PR](https://github.com/PostHog/charts/pull/15073) · [Review summary](https://github.com/PostHog/charts/pull/15073#issuecomment-5513771715)

- Private repo: details withheld. Verdict miss: zero findings.

### INC-564 · Major · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/39920) · [Fix PR](https://github.com/PostHog/posthog/pull/40164) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93650) · [Review summary](https://github.com/PostHog/posthog/pull/93650#issuecomment-5513488779)

- **Bug:** The replay playlist lost its fixed viewport height and used flex-grow under a min-height-only root. A long recordings list then made the page and player grow far past the viewport.
- **Fix:** #40164 is a straight revert. It restored the SessionRecordingPlaylistHeightWrapper with its fixed viewport height, put height 100% back on the playlist, and restored the full-scene-height layout branch. No re-land named.
- **ReviewHog posted instead:** Two published findings on SessionRecordingPlayer.tsx: the new minimum height clips player controls in notebooks. Cinema mode on screens under 1200px wide can collapse the frame to zero height.
- **How they relate:** Nothing on this. The closest finding noted the fixed heights were gone, but blamed cinema mode below 1200px and predicted a zero-height frame. Its fix, a cascade change and a cinema-mode test, would not bound the playlist in normal mode.

### INC-271 · Minor · ❌ miss · private repo

[Introducing PR](https://github.com/PostHog/charts/pull/2415) · [Fix PR](https://github.com/PostHog/charts/pull/2417) · [Resurrected PR](https://github.com/PostHog/charts/pull/15074) · [Review summary](https://github.com/PostHog/charts/pull/15074#issuecomment-5514342120)

- Private repo: details withheld. Verdict miss: zero findings.

### INC-384 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/30851) · [Fix PR](https://github.com/PostHog/posthog/pull/31399) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93663) · [Review summary](https://github.com/PostHog/posthog/pull/93663#issuecomment-5514341017)

- **Bug:** Person page events query moved into a useState initializer above the person-loaded guard. It captured an undefined person id once, so the Events tab query ran without a person filter.
- **Fix:** #31399 is a bare revert. It removed the useState and rebuilt the query inline after the person-loaded guard, using the real person id, so the query never runs without a person filter.
- **ReviewHog posted instead:** No published findings. One dismissed finding on the same lines said each table edit re-renders the whole person scene, which is avoidable work.
- **How they relate:** Nothing relevant. The dismissed render-cost finding sat on the same lines but never mentioned the undefined person id or the unscoped query. Its useMemo suggestion targeted render cost, not the person id, and the validator dropped it as a micro-optimization.

### INC-536 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/39311) · [Fix PR](https://github.com/PostHog/posthog/pull/39420) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93653) · [Review summary](https://github.com/PostHog/posthog/pull/93653#issuecomment-5514337058)

- **Bug:** The person page query in personsLogic.tsx moved the person filter outside the subquery that groups distinct_ids, so ClickHouse first aggregated every distinct_id row for the whole team.
- **Fix:** #39420 rewrote the query so the inner subquery only reads distinct_ids that belong to that person, and checks the person again in HAVING. The GROUP BY never scans the whole team.
- **ReviewHog posted instead:** Posted "No issues to report." Zero findings and zero dismissed findings on the one-line query rewrite.
- **How they relate:** Nothing on this; the bug needed the person filter pushed back inside the aggregating subquery. The routing step even wrote "GROUP BY over full table" as its reason, and the one raw finding it produced was dropped as a duplicate of the existing bot thread before validation.

### INC-542 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/39299) · [Fix PR](https://github.com/PostHog/posthog/pull/39497) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93651) · [Review summary](https://github.com/PostHog/posthog/pull/93651#issuecomment-5514321946)

- **Bug:** #39299 edited an already-applied migration and re-added the AgentDefinition model without a new migration. Django then expected a table the database had dropped, so Django's migration state no longer matched the production schema.
- **Fix:** #39497 reverted the change in full. It restored the two dropped operations in migration 0006, deleted the re-added model and field, and removed the new task endpoints. No re-land is recorded.
- **ReviewHog posted instead:** 8 findings and 9 dismissed, all on the API views, serializers, or git activities. Nothing on the migration edit or the model re-add.
- **How they relate:** Nothing on this. The bug needed someone to notice that migration 0006 was already applied, so editing it changed nothing in production. ReviewHog was given the migration file but only flagged unrelated API validation, concurrency, and logging issues.

### INC-611 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/41889) · [Fix PR](https://github.com/PostHog/posthog/pull/41919) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93649) · [Review summary](https://github.com/PostHog/posthog/pull/93649#issuecomment-5513477866)

- **Bug:** The scene title textarea's height callback set state that toggled the textarea's own positioning classes. Each measurement flipped layout and re-fired the callback until React stopped it; the revert says it broke cohort pages.
- **Fix:** #41919 is a full revert of #41889 across 210 files. It removes the multiline state, the onHeightChange callback in the title component, and the matching textarea prop. No re-land is named.
- **ReviewHog posted instead:** Four findings on SceneTitleSection.tsx: read-only title submits forms, force-edit read-only trap, stale save-on-blur state, wrong ARIA role. One dismissed. None mention the height callback or a render loop.
- **How they relate:** No finding names the height callback, the state it sets, or the class feedback loop. The closest one only hides the textarea for read-only users; cohort pages are editable, so the looping textarea still renders and the crash ships.

### INC-622 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/42546) · [Fix PR](https://github.com/PostHog/posthog/pull/42620) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93648) · [Review summary](https://github.com/PostHog/posthog/pull/93648#issuecomment-5513464878)

- **Bug:** get_actors went from two persons-DB statements to hundreds of sequential 1000-id batches on one pooled connection. Big exports ran for minutes on one pooled connection.
- **Fix:** #42620, the linked fix, is a revert that closed unmerged the same day, so the batching stayed in production. It drops the batch constant and both batch loops and restores the two single statements.
- **ReviewHog posted instead:** Two posted and four dismissed findings, all on the new batching loops in get_actors: per-statement timeouts, duplicate distinct IDs, memory, export retries, read consistency. None mentioned pool load.
- **How they relate:** No finding named the total statement count or the connection hold time. ReviewHog treated the batches as a fix to harden; two dismissed findings asked for retries and a repeatable-read transaction, which add DB load. Prevention needed fewer statements and shorter connection hold time.

### INC-828 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog/pull/57093) · [Fix PR](https://github.com/PostHog/posthog/pull/57285) · [Resurrected PR](https://github.com/PostHog/posthog/pull/93639) · [Review summary](https://github.com/PostHog/posthog/pull/93639#issuecomment-5513761411)

- **Bug:** Stage-one min/max bounds query has no GROUP BY, so it always returns one row. The fallback to the shared events table never fires; traces stored only in events are never looked up there.
- **Fix:** #57285 is a straight revert. Trace lookup went back to one query with a fixed 10-minute capture window. A later re-land, #72421, kept one query but extended the forward window to seven days.
- **ReviewHog found, validator dismissed, never posted:** The fallback helper accepts any nonempty dedicated result as complete. If a trace straddles ai_events retention, stage one returns partial bounds and stage two omits older spans left in events.
- **How they relate:** Nothing posted on this; the three published findings covered other issues, the closest being date_from truncation. This dismissed finding hit the same fallback call and the split-tables precondition, not the one-row placeholder. Its merge fix would not have caught a null or epoch minimum.

### INC-975 · Minor · ❌ miss

[Introducing PR](https://github.com/PostHog/posthog-js/pull/4224) · [Fix PR](https://github.com/PostHog/posthog-js/pull/4407) · [Resurrected PR](https://github.com/PostHog/posthog-js/pull/4750) · [Review summary](https://github.com/PostHog/posthog-js/pull/4750#issuecomment-5513744998)

- **Bug:** #4224 let the replay recorder restart and flush on session rotation while its idle state was still 'unknown', with no user interaction yet. Untouched tabs shipped a recording every rotation.
- **Fix:** #4407 makes a session born from an idle rotation hold its buffer instead of flushing. The first user interaction or an event trigger match releases it. A further rotation, stop, or unload discards it.
- **ReviewHog posted instead:** Two published findings on the recorder file: URL-trigger activation wiped on restart, and old-session data lost at rotation. Two dismissed: a useless 2 s timer and unbounded buffer memory.
- **How they relate:** Nothing on this. Every finding treats data loss, wasted timers, or memory as the risk. The closest one asked to stop re-arming a suppressed timer, which ships nothing anyway. None asks whether a session nobody touched should ship at all.
