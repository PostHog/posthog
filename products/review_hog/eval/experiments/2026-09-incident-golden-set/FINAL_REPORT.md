# Incident golden set: would ReviewHog have caught the PR that caused the incident?

> 35 real incidents mapped to their introducing PRs · 34 PRs resurrected as live PRs · 33 reviewed to completion by production ReviewHog · judged 2026-09-02/03.
> Two blind LLM judges plus an arbiter per incident; every quoted finding verified as a verbatim substring of the review payload.
> **Verdicts are LLM-judged, not human-judged.** The per-incident evidence (internal, not committed) lives in `playground/reviewhog-golden-set/verdicts.md`; spot-check it before acting on a close call.

## TL;DR

1. **About 17.5 of 33 incidents (53%) would likely not have happened.** ReviewHog posted a finding that names the incident's root cause on the incident's code path in 13 cases (39%; acting on the suggestion would have prevented the incident). In a further 9 (27%) it flagged the dangerous area, symptom, or a precondition on the PR without the mechanism (`partial`), in a way a human reviewer would likely have dug into; counting those at half weight gives the 17.5. 11 (33%) were clean misses.
2. **The validator and the publish threshold cost almost nothing.** Counting every finding ReviewHog produced, including validator-dismissed ones, moves only one incident, from miss to partial (INC-828, whose closest finding the validator dismissed). The run's urgency threshold was `consider`, so every validated finding was posted to the PR, `consider` ones included; nothing sat below the publish line. No hit was lost anywhere in the funnel. Published precision is where the pipeline's precision-over-recall design says it should be.
3. **Hits cluster on bugs a careful reader can derive from the diff plus framework semantics**: Temporal replay determinism, kea mount ordering, React reconciliation, PgBouncer transaction pooling, ClickHouse cluster fan-out cost, incremental-cursor semantics, plus two infrastructure-config hits in the private repos. **Misses cluster on bugs that need knowledge the diff does not carry**: what the runtime environment looks like around a small config change (both zero-finding private-repo misses), how ClickHouse plans a one-line HogQL rewrite, what state production already holds (legacy rows without a backfill, orgs already over quota at deploy time), and subtle frontend state machines (a `useState` initializer running before data loads, a height callback writing back into its own layout classes, a CSS height chain).
4. **Three of the eleven published misses are zero-finding reviews on tiny config diffs** (two small config changes in a private repo and a 1-line query rewrite). Two of those are the only incidents in the set from the private `charts` repo that missed. Size is the wrong signal for risk on infra PRs.
5. **Other bots were already on every PR, and ReviewHog is built not to repeat them.** Greptile (plus Veria and Parameter on some PRs) commented before ReviewHog started on all 33 PRs. Judged by the same rubric the other bots alone score 7.5/33 (23%); either reviewer together reaches 22.5/33 (68%). Four incidents the bots caught show ReviewHog explicitly building on the bot's thread instead of restating the bug, so ReviewHog's recall without the other bots present is most plausibly about 20.5/33 (62%). See "Other reviewers on the same PRs".
6. **Memorization is a real contamination channel but did not manufacture hits.** The sandbox clones the current repo, so the later fix sits in git history, and validator notes read a later state of the file (`origin/master`) in 8 of the 33 reviews, in four of them saying outright that master carries the finding's fix. None of the 13 hit findings cites a future state themselves; 4 carry a `possible` flag on proximity alone. The two `likely` flags sit on a partial and a miss.

## Headline numbers

`Weighted` is the headline prevention estimate: hit = 1, partial = ½, miss = 0. Use it when comparing reruns; the strict hit count and the hit+partial count are both kept so nobody has to re-derive them.

| Score                                               | n   | hit | partial | miss | hit+partial | weighted (partial = ½) |
| --------------------------------------------------- | --- | --- | ------- | ---- | ----------- | ---------------------- |
| Published (what a human saw on the PR)              | 33  | 13  | 9       | 11   | 22 (67%)    | **17.5 (53%)**         |
| Funnel (every finding incl. `consider` + dismissed) | 33  | 13  | 10      | 10   | 23 (70%)    | 18.0 (55%)             |

By severity (published / funnel):

| Severity | n   | published hit | published partial | published miss | published weighted | funnel hit | funnel partial | funnel miss | funnel weighted |
| -------- | --- | ------------- | ----------------- | -------------- | ------------------ | ---------- | -------------- | ----------- | --------------- |
| Critical | 3   | 1             | 0                 | 2              | 1.0 (33%)          | 1          | 0              | 2           | 1.0 (33%)       |
| Major    | 12  | 6             | 5                 | 1              | 8.5 (71%)          | 6          | 5              | 1           | 8.5 (71%)       |
| Minor    | 18  | 6             | 4                 | 8              | 8.0 (44%)          | 6          | 5              | 7           | 8.5 (47%)       |

By repo (published / funnel):

| Repo                          | n   | published hit | published partial | published miss | published weighted | funnel hit | funnel partial | funnel miss | funnel weighted |
| ----------------------------- | --- | ------------- | ----------------- | -------------- | ------------------ | ---------- | -------------- | ----------- | --------------- |
| posthog                       | 26  | 11            | 7                 | 8              | 14.5 (56%)         | 11         | 8              | 7           | 15.0 (58%)      |
| charts (private)              | 4   | 1             | 1                 | 2              | 1.5 (38%)          | 1          | 1              | 2           | 1.5 (38%)       |
| posthog-cloud-infra (private) | 2   | 1             | 1                 | 0              | 1.5 (75%)          | 1          | 1              | 0           | 1.5 (75%)       |
| posthog-js                    | 1   | 0             | 0                 | 1              | 0.0                | 0          | 0              | 1           | 0.0             |

Reading the severity split: Major incidents did best (11 of 12 at least partial). The two Critical misses are a zero-finding review on a small config change in a private repo and a review that raised findings on adjacent code in the same PR but did not flag the change that caused the incident. Minor incidents miss most often; those misses split between the environment-knowledge and frontend-state-machine classes below.

## Verdict table

Findings column is `must_fix / should_fix / consider / dismissed` as counted by the review. `Published` counts every validated finding: the run's urgency threshold was `consider`, so must_fix, should_fix and consider findings were all posted to the PR. `Funnel` adds the validator-dismissed findings. `Funnel loss` names the stage that hid the funnel match from humans. `Memorization` is the judge's suspicion that the reviewer knew the bug from training data or from the fix in git history (see Caveats).

| Incident | Sev      | Repo                | Introducing PR                                                                            | Resurrected PR                                                                              | Findings          | Published     | Funnel        | Funnel loss         | Memorization |
| -------- | -------- | ------------------- | ----------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ----------------- | ------------- | ------------- | ------------------- | ------------ |
| INC-990  | Major    | posthog             | [posthog/pull/83059](https://github.com/PostHog/posthog/pull/83059)                       | [posthog/pull/93633](https://github.com/PostHog/posthog/pull/93633)                         | 0/2/1/3           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-987  | Minor    | posthog             | [posthog/pull/72913](https://github.com/PostHog/posthog/pull/72913)                       | [posthog/pull/93635](https://github.com/PostHog/posthog/pull/93635)                         | 8/6/2/7           | 🟡 partial    | 🟡 partial    |                     | likely       |
| INC-975  | Minor    | posthog-js          | [posthog-js/pull/4224](https://github.com/PostHog/posthog-js/pull/4224)                   | [posthog-js/pull/4750](https://github.com/PostHog/posthog-js/pull/4750)                     | 0/1/1/2           | ❌ miss       | ❌ miss       |                     |              |
| INC-938  | Major    | posthog             | [posthog/pull/63600](https://github.com/PostHog/posthog/pull/63600)                       | [posthog/pull/93636](https://github.com/PostHog/posthog/pull/93636)                         | 5/8/1/1           | ✅ hit        | ✅ hit        |                     | possible     |
| INC-931  | Minor    | posthog             | [posthog/pull/65999](https://github.com/PostHog/posthog/pull/65999)                       | [posthog/pull/93637](https://github.com/PostHog/posthog/pull/93637)                         | 3/10/7/3          | ✅ hit        | ✅ hit        |                     | possible     |
| INC-834  | Major    | posthog             | [posthog/pull/57782](https://github.com/PostHog/posthog/pull/57782)                       | [posthog/pull/93638](https://github.com/PostHog/posthog/pull/93638)                         | 2/1/0/3           | ✅ hit        | ✅ hit        |                     |              |
| INC-828  | Minor    | posthog             | [posthog/pull/57093](https://github.com/PostHog/posthog/pull/57093)                       | [posthog/pull/93639](https://github.com/PostHog/posthog/pull/93639)                         | 0/1/2/2           | ❌ miss       | 🟡 partial    | validator dismissed |              |
| INC-815  | Minor    | posthog             | [posthog/pull/55662](https://github.com/PostHog/posthog/pull/55662)                       | [posthog/pull/93641](https://github.com/PostHog/posthog/pull/93641)                         | 3/2/0/3           | ✅ hit        | ✅ hit        |                     | possible     |
| INC-814  | Major    | charts              | [charts/pull/10224](https://github.com/PostHog/charts/pull/10224)                         | [charts/pull/15072](https://github.com/PostHog/charts/pull/15072)                           | 2/1/0/0           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-775  | Critical | charts              | [charts/pull/9360](https://github.com/PostHog/charts/pull/9360)                           | [charts/pull/15073](https://github.com/PostHog/charts/pull/15073)                           | 0/0/0/0           | ❌ miss       | ❌ miss       |                     |              |
| INC-717  | Major    | posthog             | [posthog/pull/48173](https://github.com/PostHog/posthog/pull/48173)                       | [posthog/pull/93643](https://github.com/PostHog/posthog/pull/93643)                         | 0/2/2/2           | ✅ hit        | ✅ hit        |                     |              |
| INC-711  | Minor    | posthog-cloud-infra | [posthog-cloud-infra/pull/6645](https://github.com/PostHog/posthog-cloud-infra/pull/6645) | [posthog-cloud-infra/pull/10210](https://github.com/PostHog/posthog-cloud-infra/pull/10210) | 1/0/0/1           | ✅ hit        | ✅ hit        |                     |              |
| INC-702  | Minor    | posthog             | [posthog/pull/44198](https://github.com/PostHog/posthog/pull/44198)                       | [posthog/pull/93644](https://github.com/PostHog/posthog/pull/93644)                         | 5/6/5/4           | ✅ hit        | ✅ hit        |                     | possible     |
| INC-694  | Minor    | posthog             | [posthog/pull/45814](https://github.com/PostHog/posthog/pull/45814)                       | [posthog/pull/93645](https://github.com/PostHog/posthog/pull/93645)                         | 1/0/0/0           | ✅ hit        | ✅ hit        |                     |              |
| INC-622  | Minor    | posthog             | [posthog/pull/42546](https://github.com/PostHog/posthog/pull/42546)                       | [posthog/pull/93648](https://github.com/PostHog/posthog/pull/93648)                         | 0/1/1/4           | ❌ miss       | ❌ miss       |                     |              |
| INC-611  | Minor    | posthog             | [posthog/pull/41889](https://github.com/PostHog/posthog/pull/41889)                       | [posthog/pull/93649](https://github.com/PostHog/posthog/pull/93649)                         | 1/3/0/1           | ❌ miss       | ❌ miss       |                     |              |
| INC-564  | Major    | posthog             | [posthog/pull/39920](https://github.com/PostHog/posthog/pull/39920)                       | [posthog/pull/93650](https://github.com/PostHog/posthog/pull/93650)                         | 0/2/0/1           | ❌ miss       | ❌ miss       |                     |              |
| INC-563  | Minor    | posthog-cloud-infra | [posthog-cloud-infra/pull/5476](https://github.com/PostHog/posthog-cloud-infra/pull/5476) | [posthog-cloud-infra/pull/10211](https://github.com/PostHog/posthog-cloud-infra/pull/10211) | 1/1/0/1           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-542  | Minor    | posthog             | [posthog/pull/39299](https://github.com/PostHog/posthog/pull/39299)                       | [posthog/pull/93651](https://github.com/PostHog/posthog/pull/93651)                         | 1/4/3/9           | ❌ miss       | ❌ miss       |                     |              |
| INC-536  | Minor    | posthog             | [posthog/pull/39311](https://github.com/PostHog/posthog/pull/39311)                       | [posthog/pull/93653](https://github.com/PostHog/posthog/pull/93653)                         | 0/0/0/0           | ❌ miss       | ❌ miss       |                     |              |
| INC-496  | Minor    | posthog             | [posthog/pull/36834](https://github.com/PostHog/posthog/pull/36834)                       | [posthog/pull/93656](https://github.com/PostHog/posthog/pull/93656)                         | 5/5/2/1           | 🟡 partial    | 🟡 partial    |                     | possible     |
| INC-488  | Critical | posthog             | [posthog/pull/26822](https://github.com/PostHog/posthog/pull/26822)                       | [posthog/pull/93657](https://github.com/PostHog/posthog/pull/93657)                         | 2/1/2/1           | ❌ miss       | ❌ miss       |                     | likely       |
| INC-487  | Major    | posthog             | [posthog/pull/36448](https://github.com/PostHog/posthog/pull/36448)                       | [posthog/pull/93658](https://github.com/PostHog/posthog/pull/93658)                         | 2/1/1/1           | ✅ hit        | ✅ hit        |                     |              |
| INC-392  | Critical | posthog             | [posthog/pull/32065](https://github.com/PostHog/posthog/pull/32065)                       | [posthog/pull/93659](https://github.com/PostHog/posthog/pull/93659)                         | 4/5/1/4           | ✅ hit        | ✅ hit        |                     |              |
| INC-390  | Major    | posthog             | [posthog/pull/31685](https://github.com/PostHog/posthog/pull/31685)                       | [posthog/pull/93660](https://github.com/PostHog/posthog/pull/93660)                         | 4/5/0/3           | ✅ hit        | ✅ hit        |                     |              |
| INC-384  | Minor    | posthog             | [posthog/pull/30851](https://github.com/PostHog/posthog/pull/30851)                       | [posthog/pull/93663](https://github.com/PostHog/posthog/pull/93663)                         | 0/0/0/1           | ❌ miss       | ❌ miss       |                     |              |
| INC-271  | Minor    | charts              | [charts/pull/2415](https://github.com/PostHog/charts/pull/2415)                           | [charts/pull/15074](https://github.com/PostHog/charts/pull/15074)                           | 0/0/0/0           | ❌ miss       | ❌ miss       |                     |              |
| INC-242  | Major    | posthog             | [posthog/pull/25129](https://github.com/PostHog/posthog/pull/25129)                       | [posthog/pull/93668](https://github.com/PostHog/posthog/pull/93668)                         | 4/2/0/2           | 🟡 partial    | 🟡 partial    |                     | possible     |
| INC-239  | Minor    | charts              | [charts/pull/1810](https://github.com/PostHog/charts/pull/1810)                           | [charts/pull/15075](https://github.com/PostHog/charts/pull/15075)                           | 0/4/1/2           | ✅ hit        | ✅ hit        |                     |              |
| INC-218  | Major    | posthog             | [posthog/pull/23808](https://github.com/PostHog/posthog/pull/23808)                       | [posthog/pull/93670](https://github.com/PostHog/posthog/pull/93670)                         | 0/3/0/5           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-193  | Major    | posthog             | [posthog/pull/22181](https://github.com/PostHog/posthog/pull/22181)                       | [posthog/pull/93671](https://github.com/PostHog/posthog/pull/93671)                         | 4/1/0/3           | ✅ hit        | ✅ hit        |                     |              |
| INC-154  | Minor    | posthog             | [posthog/pull/19938](https://github.com/PostHog/posthog/pull/19938)                       | [posthog/pull/93673](https://github.com/PostHog/posthog/pull/93673)                         | 2/2/1/4           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-120  | Major    | posthog             | [posthog/pull/17466](https://github.com/PostHog/posthog/pull/17466)                       | [posthog/pull/93676](https://github.com/PostHog/posthog/pull/93676)                         | 0/5/0/1           | 🟡 partial    | 🟡 partial    |                     |              |
| INC-921  | Major    | posthog             | [posthog/pull/63988](https://github.com/PostHog/posthog/pull/63988)                       | [posthog/pull/93680](https://github.com/PostHog/posthog/pull/93680)                         | review terminated | not evaluable | not evaluable |                     |              |
| INC-284  | Minor    | posthog-js-lite     | [posthog-js-lite/pull/315](https://github.com/PostHog/posthog-js-lite/pull/315)           | not created                                                                                 |                   | not evaluable | not evaluable |                     |              |

Not evaluable:

- **INC-921**: the resurrected PR has 446 files / 70k additions. ReviewHog terminated the review as excessive before validation, so there are no validated findings, and the terminated report is not retrievable through the reviews API (404). No raw-coverage aside is possible.
- **INC-284**: `posthog-js-lite` is archived and rejects all writes, so the PR could not be resurrected.

`scores.csv` in this directory holds the same table in machine-readable form, with the ReviewHog report ids.

## What the hits and misses look like (public repos only)

Bugs are described only in terms visible in the public introducing and fix PRs. The `charts` and `posthog-cloud-infra` rows are aggregated above and deliberately not described here.

### Hits (13)

| Incident | What the PR did and what ReviewHog said                                                                                                                                                                                                                                                                                                         |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| INC-938  | Managed-view DAG placement took a session-scoped `pg_advisory_lock` across autocommit statements on a pooled connection. ReviewHog (must_fix) named the transaction-pooling mechanism: the unlock can land on a different backend, the lock leaks, waiters block. The fix PR (#66932) dropped the session lock.                                 |
| INC-931  | The shared Tooltip gained a lazy path that swapped the element rendered at the trigger's tree position once the open delay elapsed. ReviewHog (must_fix) traced the React reconciliation: different element types at one tree position replace the focused control's DOM node. Fixed by reverting lazy mounting (#66215).                       |
| INC-834  | The exporter bundle split swapped `logic.actions` for `useActions(logic)` in the shared-dashboard auto-refresh, which mounted `dashboardLogic` before the sibling `<Dashboard>` supplied the serialized dashboard. ReviewHog (must_fix) named exactly that mount-order defect and the extra dashboard request the shared scene then depends on. |
| INC-815  | A new Temporal activity was scheduled ahead of an existing one in the tasks workflow with no `workflow.patched()` gate. ReviewHog (must_fix) named the replay nondeterminism for in-flight histories and the exact patch-gate remedy the fix (#56117) applied.                                                                                  |
| INC-717  | New taxonomic-filter value groups fired unfiltered ClickHouse value queries on every picker open and search. ReviewHog (should_fix) named the mount-time fan-out and the unbounded person-property scan; the re-landed version added a minimum search length and an event filter.                                                               |
| INC-702  | A `phs_` guard in the shared personal-API-key finder raised instead of returning `None`, breaking valid legacy secret-token requests on the local-evaluation endpoint. ReviewHog (must_fix) named the throttle path that re-enters the key finder. The PR was reverted.                                                                         |
| INC-694  | The Google Ads incremental filter moved from `>=` to `>` on a date-bucket cursor whose current value is the still-open day. ReviewHog (must_fix, the only finding on a 1-line diff) named exactly that: the open day is written back as the cursor and never re-read. Reverted in #46233.                                                       |
| INC-487  | Forwarding the events exclusion list to the event-definitions endpoint sent the `[null]` sentinel existing pickers use to hide "All events", producing invalid SQL. ReviewHog (must_fix) named the three callers, the sentinel, and the resulting 500.                                                                                          |
| INC-392  | A flag-gated SSE endpoint was replaced with an unflagged progress endpoint that probed a cluster-wide `system.processes` table once per second for every blocking query. ReviewHog (must_fix) named the orphaned streams and the per-query cluster-wide probe cost. Fully reverted in #32173.                                                   |
| INC-390  | A survey-submission dedup subquery over `events` with no team or time bound was embedded into every survey-results query. ReviewHog named the unbounded scan (should_fix) and, separately, the missing tenant guard on the raw subquery (must_fix). Reverted and re-landed with a single-scan query.                                            |
| INC-193  | Loosening the dashboard cached-result guard let result-less tiles enter `loadData` from `propsChanged`, which re-renders, which aborts, which cancels. ReviewHog (must_fix) named the continuous request-and-cancel loop on that exact hunk. Reverted in #22187.                                                                                |
| INC-711  | private repo (posthog-cloud-infra): verdict only. The single must_fix finding sits on the incident's lines and names its mechanism; details withheld.                                                                                                                                                                                           |
| INC-239  | private repo (charts): verdict only. A should_fix finding sits on the incident's lines and names its mechanism; details withheld.                                                                                                                                                                                                               |

### Partials (9)

| Incident | Why not a hit                                                                                                                                                                                                                                                                                                                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| INC-990  | Sender override made a stored placeholder address load-bearing; existing steps carrying it failed every send. ReviewHog (validated at `consider`, posted with that badge) flagged the exact throw site, an address off the sender's verified domain failing every send, but assumed the value had just been typed in the new editor rather than already stored on existing steps.    |
| INC-987  | Secret inputs moved to an encrypted column without a backfill, so re-saving a legacy flow dropped the secret. ReviewHog's must_fix sits on the same save path and the same recovery map, but its trigger is a lenient-draft branch, not the ordinary re-save of a pre-existing row. Flagged `likely` memorized: the validator note cites `origin/master` and names the fix's helper. |
| INC-496  | 2FA enforcement applied to SSO-authenticated sessions. ReviewHog (must_fix) states that SSO sessions enter enforcement unverified, but treats that as intended and attacks the verification endpoint instead of the missing SSO exemption.                                                                                                                                           |
| INC-242  | Celery beat entries registered with `crontab(<five-field string>)` instead of the `get_crontab` helper. One validator bullet names the exact defective call and the exact remedy, but as an aside inside a finding about a beat-schedule key collision. Flagged `possible` memorized: the finding body presupposes "the cron parser fix".                                            |
| INC-218  | Async initial insight load plus resuming incomplete cached statuses, with no gate on whether the query had changed (the gate the re-land added). ReviewHog (should_fix) traced the shared query id into the cancel path but framed it as one viewer cancelling another's refresh, not as an ungated re-fire on every prop change.                                                    |
| INC-154  | A grace window moved over-quota tokens into a new Redis set while capture kept reading the old one. ReviewHog (must_fix) named the routing that moved tokens out of the limiter set, but its stated trigger is daily usage refreshes, not the first post-deploy run.                                                                                                                 |
| INC-120  | A ClickHouse migration added a `SELECT *` projection and materialized it for the live partition at deploy time. ReviewHog posted five should_fix findings on the migration, including "run the backfill as a controlled async migration", but framed the risk as unobserved failure rather than deploy-time load.                                                                    |
| INC-814  | private repo (charts): verdict only. The review named the incident's area with a different explanation of the mechanism; details withheld.                                                                                                                                                                                                                                           |
| INC-563  | private repo (posthog-cloud-infra): verdict only. The review named the incident's area but attributed the problem elsewhere; details withheld.                                                                                                                                                                                                                                       |

### Misses (11)

| Incident | What was missed                                                                                                                                                                                                                             | Class                           |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| INC-975  | Replay recorder restarted on session rotation while idle state was still unknown, shipping recordings for tabs with no interaction. ReviewHog found two other real bugs in the same function, neither the incident's.                       | frontend state machine          |
| INC-828  | Two-stage trace lookup whose first-stage aggregate always returns a row, so the empty-result fallback to the shared events table never fires. The closest finding (partial expiry hides shared-table spans) was dismissed by the validator. | data-path fallback; funnel loss |
| INC-775  | Small config change (private repo). Zero findings.                                                                                                                                                                                          | zero-finding infra diff         |
| INC-622  | Two single-statement person reads became hundreds of sequential batched statements per export. Six findings on the hunk, none about the total statement count or runtime of a full export.                                                  | operational load                |
| INC-611  | Scene title textarea: autosize height callback set state that toggled the textarea's own positioning classes, which can re-trigger the measurement. Four findings on the component, none on that feedback path.                             | frontend state machine          |
| INC-564  | Replay playlist lost its fixed viewport height and grew past the viewport. Two should_fix findings on the same height chain, but about cinema mode and notebook embeds.                                                                     | CSS layout chain                |
| INC-542  | An already-applied Django migration was edited and a model re-declared without a new migration. All 17 findings were on the API and serializers; nothing on the migration file, which was in the reviewed chunk.                            | migration state                 |
| INC-536  | 1-line HogQL rewrite moved a `person_id` filter outside an `argMax`/`GROUP BY` subquery. Zero findings.                                                                                                                                     | zero-finding query rewrite      |
| INC-488  | A new table was registered as directly queryable. The review found scoping gaps on the neighbouring lazy view (and cited `origin/master` doing so) but never checked the new registration itself.                                           | environment knowledge           |
| INC-384  | Person page events query moved into a `useState` initializer that ran before the person loaded, freezing an undefined person id. The only finding, on the same lines, was about an extra render.                                            | frontend state machine          |
| INC-271  | Small config change (private repo). Zero findings.                                                                                                                                                                                          | zero-finding infra diff         |

## Other reviewers on the same PRs: three numbers

The resurrected PRs were not clean rooms. The repos already run other automated reviewers (Greptile on every PR, Veria and Parameter on some), and every one of them posted before ReviewHog's trigger: Greptile's first comment landed 20 to 60 minutes ahead of ReviewHog on all 33 PRs, with substantive inline findings on 26. ReviewHog is built not to repeat what is already on the PR: every perspective prompt receives the existing inline comments with the instruction to raise nothing that duplicates them, and the dedup stage drops any fresh finding that matches a prior comment. So the 53% above is strictly "what ReviewHog found that nobody had posted yet", and it can only understate ReviewHog. The three numbers below separate that out. Same weighting throughout (hit = 1, partial = ½), published score, n = 33.

| #   | What it measures                                                                                | Score             |
| --- | ----------------------------------------------------------------------------------------------- | ----------------- |
| 1   | **ReviewHog as run**: findings it posted, with other bots' comments already on the PR           | **17.5/33 = 53%** |
| 2   | **ReviewHog if the other bots had been silent** (counterfactual; see the three variants below)  | **20.5/33 = 62%** |
| 3   | **Other bots alone**: their comments posted before ReviewHog started, judged by the same rubric | **7.5/33 = 23%**  |

Number 2 cannot be measured directly from this run, so it is bracketed:

| Variant of #2         | Rule                                                                                                                                                                | Score             |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------- |
| Observed only         | Credit ReviewHog with a raw finding that the dedup stage demonstrably dropped _because a bot comment already said it_ (recovered from the pipeline's LLM telemetry) | 18.0/33 = 55%     |
| **Likely (headline)** | Observed, plus incidents where the bots stated the bug and ReviewHog's own findings visibly build on the bot thread instead of restating it                         | **20.5/33 = 62%** |
| Upper bound           | Either reviewer found it (ReviewHog ∪ other bots)                                                                                                                   | 22.5/33 = 68%     |

How the overlap breaks down:

- **Other bots alone**: 6 hits, 3 partials, 24 misses. Greptile posted all six hits as inline comments; Veria contributed one partial. The bots' hits are concentrated on small, local defects (a `useState` initializer, a misparsed cron string, an unscoped table registration, a null-row aggregate).
- **Both found it**: 3 incidents (ReviewHog hit, bots partial: INC-694, INC-487, INC-392). ReviewHog restated the bug independently in each; no dedup fired.
- **Only ReviewHog**: 10 hits and 7 partials where the bots had nothing relevant (13.5/33). Adding the three shared hits and the two partials next to a bot hit gives the as-run 17.5/33 (53%).
- **Only the bots**: 4 incidents the bots hit and ReviewHog missed outright (INC-828, INC-536, INC-488, INC-384) and 2 the bots hit and ReviewHog scored partial (INC-563, INC-242). In four of these six (INC-828, INC-536, INC-563, INC-242) ReviewHog's own output explicitly builds on the bot's thread instead of restating the bug (published findings for INC-828, INC-563 and INC-242; for INC-536 the raw finding the dedup stage dropped, see below), which is the do-not-repeat instruction working as designed; those four are the "likely suppressed" credits. In the other two (INC-488, INC-384) nothing in ReviewHog's output references the thread, so they stay uncredited.

**What the telemetry shows.** The dedup stage's inputs and outputs were recovered for 29 of the 33 reviews (40 of the 45 raw findings the counters say were dropped before validation). Of those 40, only 2 were dropped against an external bot comment; 38 were dropped as duplicates of another ReviewHog finding in the same run. Five dropped raw findings were themselves hits on the incident bug (INC-931, INC-815, INC-711, INC-487, INC-390), and every one was a duplicate of a ReviewHog finding that survived and was posted, so nothing was lost there. Exactly one dropped finding would have reached validation had the bot been silent: on INC-536 (a one-line HogQL rewrite), ReviewHog raised one finding that opens with "The existing thread identifies the full-project aggregation", the dedup model marked it a duplicate of Greptile's comment, and the review shipped with zero findings. Judged on its own it is a partial, not a hit, which is why the observed-only variant moves by half a point.

| Incident | Sev      | ReviewHog (published) | Other bots (before ReviewHog) | ReviewHog vs. bot thread  | Suppression | Dropped raw finding          |
| -------- | -------- | --------------------- | ----------------------------- | ------------------------- | ----------- | ---------------------------- |
| INC-990  | Major    | 🟡 partial            | ❌ miss                       |                           |             | none relevant                |
| INC-987  | Minor    | 🟡 partial            | ❌ miss                       |                           |             | none relevant                |
| INC-975  | Minor    | ❌ miss               | ❌ miss                       |                           |             |                              |
| INC-938  | Major    | ✅ hit                | ❌ miss                       |                           |             | none relevant                |
| INC-931  | Minor    | ✅ hit                | ❌ miss                       |                           |             | ✅ hit (vs. own sibling)     |
| INC-834  | Major    | ✅ hit                | ❌ miss                       |                           |             |                              |
| INC-828  | Minor    | ❌ miss               | ✅ hit                        | builds on the thread      | likely      | none relevant                |
| INC-815  | Minor    | ✅ hit                | ❌ miss                       |                           |             | ✅ hit (vs. own sibling)     |
| INC-814  | Major    | 🟡 partial            | ❌ miss                       |                           |             |                              |
| INC-775  | Critical | ❌ miss               | ❌ miss                       |                           |             |                              |
| INC-717  | Major    | ✅ hit                | ❌ miss                       |                           |             |                              |
| INC-711  | Minor    | ✅ hit                | ❌ miss                       |                           |             | ✅ hit (vs. own sibling)     |
| INC-702  | Minor    | ✅ hit                | ❌ miss                       |                           |             | none relevant                |
| INC-694  | Minor    | ✅ hit                | 🟡 partial                    | restates it independently |             |                              |
| INC-622  | Minor    | ❌ miss               | ❌ miss                       |                           |             |                              |
| INC-611  | Minor    | ❌ miss               | ❌ miss                       |                           |             | none relevant                |
| INC-564  | Major    | ❌ miss               | ❌ miss                       |                           |             |                              |
| INC-563  | Minor    | 🟡 partial            | ✅ hit                        | builds on the thread      | likely      |                              |
| INC-542  | Minor    | ❌ miss               | ❌ miss                       | builds on the thread      |             | none relevant                |
| INC-536  | Minor    | ❌ miss               | ✅ hit                        | builds on the thread      | likely      | 🟡 partial (vs. bot comment) |
| INC-496  | Minor    | 🟡 partial            | ❌ miss                       |                           |             | none relevant                |
| INC-488  | Critical | ❌ miss               | ✅ hit                        |                           | possible    |                              |
| INC-487  | Major    | ✅ hit                | 🟡 partial                    | restates it independently |             | ✅ hit (vs. own sibling)     |
| INC-392  | Critical | ✅ hit                | 🟡 partial                    | restates it independently |             | 🟡 partial (vs. own sibling) |
| INC-390  | Major    | ✅ hit                | ❌ miss                       |                           |             | ✅ hit (vs. own sibling)     |
| INC-384  | Minor    | ❌ miss               | ✅ hit                        |                           | possible    |                              |
| INC-271  | Minor    | ❌ miss               | ❌ miss                       |                           |             |                              |
| INC-242  | Major    | 🟡 partial            | ✅ hit                        | builds on the thread      | likely      | none relevant                |
| INC-239  | Minor    | ✅ hit                | ❌ miss                       |                           |             |                              |
| INC-218  | Major    | 🟡 partial            | ❌ miss                       |                           |             | 🟡 partial (vs. own sibling) |
| INC-193  | Major    | ✅ hit                | ❌ miss                       | restates it independently |             | none relevant                |
| INC-154  | Minor    | 🟡 partial            | ❌ miss                       | builds on the thread      |             | none relevant                |
| INC-120  | Major    | 🟡 partial            | ❌ miss                       |                           |             |                              |

**Reading the three numbers.** On these 33 PRs, ReviewHog alone would likely have prevented about 53% of the incidents, the other bots about 23%, and the two together about 68%. ReviewHog's own recall without the other bots present is somewhere between 55% and 68%, most plausibly around 62%. The 53% is the honest "as deployed today" figure; the 62% is the figure to compare against a rerun where ReviewHog reviews first.

## Funnel-loss analysis

Only one incident differs between the published and funnel scores:

- **INC-828**: the validator dismissed the near-match as a pre-existing rollout trade-off in a shared helper. Funnel partial, published miss.

Nothing else moved. In particular:

- No hit was dismissed or downgraded out of view. Of the 23 matched findings (hits and partials, published or funnel), the validator kept the reviewer's priority on 20 and downgraded 3 (INC-563 and INC-218 must_fix to should_fix, INC-990 should_fix to consider); none fell below the publish line, because the run's urgency threshold was `consider` and the INC-990 finding was posted with that badge.
- 32 of 33 incidents have `funnel == published`.

So the funnel is not where recall is lost. The reviewer either names the mechanism (hit), circles it (partial), or does not produce a candidate at all (miss). The previous experiment (`2026-07-reviewer-topology`) reached the same conclusion from a different angle: coverage is bound by what the perspective skills look for, not by validation strictness.

## Patterns

**What ReviewHog is good at.** Every hit is a bug whose mechanism follows from reading the diff and applying documented framework or infrastructure semantics: how Temporal replays history, when kea mounts a logic, how React reconciles element types, what transaction-mode PgBouncer does to session state, what a ClickHouse `clusterAllReplicas` probe costs, how a date-bucket cursor interacts with a strict comparison. The validator notes on these hits read like a competent senior engineer's trace, with line numbers verified against the reviewed head.

**Where it misses, in order of frequency:**

1. **Environment knowledge the diff does not carry** (INC-775, INC-271, INC-536, INC-622, INC-488). What production looks like around a small config change; how ClickHouse plans a one-line query rewrite; what hundreds of sequential statements per export cost the database; who can reach a newly registered table. Three of these are zero-finding reviews on diffs of a few lines, where the perspective selector correctly routed only one perspective and it found nothing to say. **Small infra and query diffs need a different lens than "review the code", something closer to "what does production look like around this key".**
2. **State that production already holds** (INC-990, INC-987, INC-154, INC-242; all four partials). Legacy rows without a backfill, placeholder values in a field that becomes load-bearing, orgs already past quota on the first run after deploy. ReviewHog reasons about the code's steady state well and about the rollout transition poorly. The `2026-07-reviewer-topology` report flagged the same gap under "rollout / deploy-time preconditions".
3. **Frontend state machines** (INC-975, INC-611, INC-384, INC-564). A `useState` initializer capturing a loading-time value, a height callback that writes state back into the measured element's own layout classes, a rotation restart in a three-valued idle state, a percentage-height chain losing its definite ancestor. In three of these four the review found other real bugs on the same lines and still missed the one that shipped.
4. **Migration state** (INC-542). Editing an applied migration is a category of bug the current skills do not look for at all; the migration file was in the chunk and drew zero findings.

**Precision.** Where ReviewHog produced a matching finding, the arbiter could not refute the mechanism in any of the 13 hits. The 13 hit findings were reviewer must_fix in 10 cases and should_fix in 3 (INC-717, INC-390, INC-239), and the validator kept the reviewer's priority on all 13.

## Caveats

- **The reviewer may know these bugs.** ReviewHog's reviewer and validator are off-the-shelf models. The original PRs and fixes are public, and the sandbox clones the current repo, so the fix sits in git history. Validator notes read a later state of the file (`origin/master`, "upstream master", "master's much later copy") in 8 reviews (INC-987, INC-938, INC-931, INC-815, INC-717, INC-496, INC-488, INC-242), and in four of them (INC-987, INC-938, INC-931, INC-488) a note says master carries the finding's fix or "the shape the team eventually adopted". The judges flagged 2 verdicts `likely` (INC-987 partial, INC-488 miss) and 6 `possible` (INC-938, INC-931, INC-815, INC-702 hits; INC-496, INC-242 partials). For the four flagged hits the matched finding's own evidence is PR-era line numbers and repo precedents that existed at the base commit, and its wording does not mirror the fix PR; the master citations sit on sibling findings in the same review. Discounting the flagged hits anyway leaves 9 unflagged hits (27%). **A rerun should close this channel** by having the sandbox check out the base commit with no later history (shallow clone at head, or strip refs newer than the merge commit).
- **LLM judges.** Two blind judges (one fair, one instructed to start from `miss` and refute every candidate) plus an arbiter; judge A agreed with the final verdict on 32 of 33, judge B on 30 of 33; the four disagreements (INC-990, INC-702, INC-564, INC-563) were decided by the arbiter on rubric tests recorded in the internal verdict file. Every quoted finding was checked mechanically to be a verbatim substring of the review payload. Nobody human has read all 33 verdicts.
- **Attribution.** The incident list attributes each incident to one introducing PR. For two incidents the source also names an alternative PR (the judge notes this). Where the incident's auto-selected code hunk disagreed with the fix PR's target, the judge followed the fix PR.
- **Other bots commented first.** No human reviewed the resurrected PRs, but Greptile, Veria and Parameter did, before ReviewHog on every PR. ReviewHog's do-not-repeat instruction and dedup stage therefore fired against those comments; the section above quantifies the effect. A clean rerun should trigger ReviewHog before the other bots post, or disable them on the resurrected PRs.
- **One review per PR, single turn, resolution disabled.** 19 PRs carried their original commit history, 15 a single squash commit; the reviewed diff is identical either way.
- **Old bases.** Base branches range from 2023 to 2026. The reviewer read each diff against the codebase as it was then, which is the same view the original human reviewer had.

## Method

### 1. Pick incidents and map them to introducing PRs

Start from the incident list (internal; one row per incident with severity, the introducing PR, its merge commit, the file and hunk the bug lives in, and a written root cause). 35 incidents were mapped; each row names exactly one introducing PR. Where the row cites the fix PR, that PR is the strongest statement of the bug and the judge reads it.

### 2. Resurrect each introducing PR

For each incident, recreate the original PR so that ReviewHog sees the same diff a human reviewer saw at the time:

1. Create a base branch pinned at the merge commit's parent (`master-<sha7>` / `main-<sha7>`).
2. Create a head branch pinned at the merge commit. When the original commits still exist on the remote, restore them; otherwise use one squash commit. The reviewed diff is identical either way.
3. Open a ready-for-review PR head → base with the original title and body verbatim. Wrap `@mentions` in backticks so nobody gets pinged. Do not mention ReviewHog, incidents, or evaluation anywhere in the PR.
4. Leave CI on. Some resurrected branches fail CI because the base is old; this does not affect the review.

One incident (INC-284, `posthog-js-lite`) could not be resurrected because the repo is archived.

### 3. Run ReviewHog

Trigger production ReviewHog on each resurrected PR for the PostHog team, one turn per PR, resolution stage disabled, urgency threshold `consider`. Record the trigger time: other bots installed on the repo post within minutes of the PR opening, and ReviewHog treats their inline comments as existing coverage (see "Other reviewers on the same PRs"). To measure ReviewHog on its own, trigger it before they post or disable them on the resurrected PRs (every validated finding at or above the urgency threshold is posted to the PR; at `consider` that is all of them, so only validator-dismissed findings stay off the PR). Do not re-trigger while judging: a second trigger appends a new turn and changes the finding set. Reviews that terminate as too large (INC-921 here) are scored not evaluable.

### 4. Judge

Per incident, pull the review through the MCP tool `review-hog-reviews-get` (validated `findings`, `dismissed_findings` with the validator's reason, `report_markdown`). Compare every finding against the incident's root cause on code path and mechanism, not topic overlap, and assign two verdicts:

- **published**: only findings a human saw on the PR (every validated finding whose `effective_priority` is at or above the run's urgency threshold; `consider` on this run, so all of them).
- **funnel**: every finding, including `dismissed_findings`. When funnel beats published, record which stage lost it: `validator_dismissed`, or `priority_too_low` on a run whose threshold sits above `consider`.

Scale:

- **hit**: a finding names the same root cause on the same code path (mechanism, not just the file). Acting on its suggestion would have prevented the incident.
- **partial**: a finding flags the dangerous area, the symptom, or a precondition without the mechanism, in a way a reasonable human reviewer would likely have dug into.
- **miss**: nothing relevant.

Headline prevention estimate: hit = 1, partial = ½, miss = 0, summed over the evaluable incidents. Keep this weighting on reruns so the numbers stay comparable.

The comments other bots posted before ReviewHog's trigger were judged by the same rubric (one judge plus a skeptic on every non-miss), and the dedup stage's inputs and outputs were pulled from the pipeline's LLM telemetry (`$ai_generation` events tagged `ai_product=review_hog`, `ai_stage=dedup`, heavy content from `posthog.ai_events`) to see which raw findings were dropped against an external comment.

Each incident was judged by two independent LLM judges (one fair, one instructed to start from `miss` and refute every candidate), then an arbiter that re-read the evidence: it tried to refute agreed non-miss verdicts, re-scanned agreed misses for anything both judges overlooked, and decided disagreements. Each judge also ran a memorization check (does the finding mirror the fix PR's wording, does the validator note cite `master` or a later fix). Every quoted finding was verified mechanically to be a verbatim substring of the review payload. The full rubric the judges followed is [`JUDGE_RUBRIC.md`](./JUDGE_RUBRIC.md) in this directory; the internal per-incident evidence is in `playground/reviewhog-golden-set/verdicts.md` (not committed, contains incident details). The judges ran with an earlier wording of the publish rule (must_fix and should_fix only); once the run's `consider` threshold was confirmed, the one affected verdict (INC-990) was corrected to published partial, and the rubric here carries the corrected rule.

### 5. Rerunning

To rerun on the same set, re-trigger each resurrected PR (this appends a turn; judge the latest turn) and repeat step 4. To rerun on a new set, repeat from step 1. Keep the two-score rubric so results stay comparable with this report. Close the memorization channel first (see Caveats) if the goal is a clean measurement rather than a comparison with this run.

## Cost

Judging: about 20M subagent tokens across four workflow runs, of which roughly 8M were wasted by a resumed run re-executing judges the resume cache failed to replay (the cache is call-order-prefixed; a parallel pipeline calls agents in a different order each run). The final narrow run (4 judges + 30 arbiters) cost 3.7M. Lesson for the next run: write every agent's result to disk and drive resumes from the files, not from the workflow cache.

ReviewHog review cost is not tracked here; it ran as the normal production pipeline on 33 PRs.

## Recommendations

1. **Treat this set as the recall yardstick for reviewer-skill work.** 17.5/33 weighted (13 hits, 9 partials) on the published score is the as-run baseline, about 20.5/33 once the other bots' head start is discounted; the next perspective-skill round should be measured against it, and the miss classes above are the target list.
2. **Add an "environment lens" for small infra and query diffs.** Three zero-finding misses and two more in the same class share a shape: a tiny change to a config key or a query whose consequence lives outside the diff. A perspective that asks "what reads this key or table in production, and what changes for it" is the cheapest way to move those.
3. **Add a rollout-transition check.** Four incidents (all partials) turned on state production already held at deploy time. A prompt-level question ("what does the first run after deploy see that the steady state does not") would have converted at least two of them.
4. **Close the memorization channel before the next measurement**: check out the base commit without later history in the review sandbox.
5. **Cleanup after this report is accepted**: close the 34 resurrected PRs and delete their head and base branches (commands and branch names in the internal mapping file).
