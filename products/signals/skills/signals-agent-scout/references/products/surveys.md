# Lens: Surveys

Surveys are the only lens that captures **what users say**, not just what they
do. Open-text responses surface intent and emotion that other lenses can't —
why someone churned, what they expected vs got, what they wish worked
differently. NPS and rating distributions give a leading indicator of
sentiment that often shifts before retention numbers do.

The team has surveys if `products_in_use` includes `surveys` or if
`top_events` shows `survey shown` / `survey sent` / `survey dismissed`. The
volume of survey activity is usually low compared to other lenses, but the
**signal-per-event ratio is high** — one open-text response can be more
informative than thousands of pageviews.

## Quick scan from the profile alone

| Pattern                                                            | What it usually means                                                       |
| ------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `survey sent` / `survey dismissed` events stable across 7d/24h     | Healthy baseline, surveys running as configured                             |
| `survey shown` count rising but `survey sent` flat                 | Response-rate drop — survey content / fatigue / placement issue             |
| `survey shown` quiet but a survey is configured                    | Targeting issue — survey not reaching its audience, or display logic broken |
| `survey sent` `recent_24h_count / count` ≫ `1/7`                   | Today's spike — a launched survey hitting target cohort                     |
| Surveys in `surveys-get-all` with `responses_count` rising fast    | Active in-flight survey — read responses, not just metrics                  |
| Surveys `active=true` but `responses_count = 0` over multiple days | Broken instrumentation, wrong targeting, or dead audience                   |

If `surveys-get-all` shows no surveys configured, the team isn't using this
lens — pivot. If they have configured surveys but volume is too low to
analyze (typical n < 20), make a memory entry noting the survey exists and
recheck later.

## Patterns to look for

### NPS / rating shift

A rating-style survey (NPS, CSAT, thumbs) shows score distribution moving —
average dropping by ≥0.5 points, or % detractors rising materially vs the
baseline. `survey-stats` gives the per-survey aggregates; `survey-get` plus
`query-trends` on the rating property over time gives the shape. Often a
leading indicator that precedes retention drops by weeks. Cross-source
convergence with a recent product change in `activity-log-list` or a
correlated `error-tracking` issue is high-signal.

### Open-text theme shift

Open-text responses cluster around a recurring topic that wasn't dominant
before — "slow", "confusing", "missing X feature", "broken on mobile". This
is the lens's unique value: themes here surface user-perceived problems that
event analysis can't see. Use `posthog:survey-session-synthesis` to
triangulate themes with what those respondents actually did (session replays
of the same users) — said + did is much stronger than either alone.

### Response-rate drop

`survey shown` events stable but `survey sent` / completion drops — the
survey is being shown but fewer users complete it. Causes: survey content
got worse (ambiguous question, too long), survey fatigue (shown too often),
placement broke (modal triggers but is hidden / cropped). Worth emitting
when the drop is material (≥30% relative) and not explained by a survey
length / wording change.

### Survey targeting drift

A survey configured for cohort X is showing to users outside that cohort,
or vice versa — visible by comparing the survey's targeting rules
(`survey-get`) with the actual respondents' properties via
`query-trends-actors` on the `survey sent` event. Often surfaces when a
cohort definition or feature flag changes upstream of the survey targeting.

### Survey-error correlation

A user who responded poorly (low NPS, negative open text) had a session
with errors / rage clicks / failed actions. The synthesis playbook
(`posthog:survey-session-synthesis`) is the canonical path here —
combining what the user said with what they actually experienced, on a
budget. Findings from this pattern are unusually strong because they have
both qualitative and quantitative evidence.

### New / recurring complaint topic

Open-text responses contain a topic that didn't appear in the prior 30
days. Worth a memory entry as a leading-indicator; worth a finding only if
multiple respondents independently raise it within a short window. The
distinction between "one frustrated user" and "emerging pattern" is what
makes this signal vs noise.

## Disqualifiers

- **Low-n surveys** — fewer than ~20 responses isn't a trend, it's
  anecdotal. Note the survey exists and recheck later.
- **Brand-new survey (< 7d)** — no baseline to compare to. Wait for a
  baseline week.
- **Demo / internal accounts** — internal users often complete surveys at
  much higher rates than real users; their responses skew distributions.
  Filter via email domain or known internal cohort.
- **Survey just changed wording** — score shifts after a wording change
  aren't sentiment shifts; they're survey-design shifts. Worth a memory
  entry recording when wording changed.
- **Single-respondent open-text** — one person complaining isn't a theme
  unless the wording is unusually specific (e.g. naming a specific page or
  feature). Pivot to recurrence before weighing.
- **Survey shown but instrumentation incomplete** — sometimes
  `survey shown` fires but the response payload doesn't have the answer
  property. That's an SDK / config issue, not a sentiment signal. Use
  `posthog:survey-sdk-audit` to confirm before drilling.
- **Existing tracked complaint** — if memory already records a known issue
  the team is working on, don't re-emit unless new evidence advances the
  picture (volume jump, new affected segment).

When in doubt, write a memory entry instead of emitting.

## MCP tools

- `surveys-get-all` — start here. List active surveys; filter by status
  and targeting.
- `survey-get` — single survey detail, including questions, targeting,
  and response cap.
- `survey-stats` — per-survey aggregates: response count, completion
  rate, rating distribution.
- `surveys-global-stats` — all surveys' aggregates at once. Useful for
  cross-survey baseline comparison.
- `query-trends` on `survey shown` / `survey sent` / `survey dismissed`
  events — over time, with breakdowns by survey id, cohort, or
  response value.
- `query-trends-actors` — pivot from "rating moved" to "which respondents
  drove it".
- `read-data-schema event_property_values` — confirm the survey's
  response property name (often `$survey_response_<question_id>` or a
  team-defined slug) before constructing aggregations.
- `session-recording-summarize` — when triangulating an open-text response
  with what the respondent actually did (the synthesis pattern). Use the
  session-replay lens's tools alongside.

For deep investigation playbooks, the sandbox image bakes
`posthog:survey-session-synthesis` (triangulating open-text themes with
session replays of the same respondents on a budget — the canonical pattern
for this lens) and `posthog:survey-sdk-audit` (auditing survey SDK features
and version requirements when instrumentation looks incomplete). Lean on
those rather than re-deriving the synthesis order.

## Memory shapes worth writing

After investigating surveys on a project, leave durable steers like:

- _"Team's NPS rolling 30d baseline is 32, normal range 28-36; drops below
  25 are worth flagging."_ (`pattern`, `domain:surveys`,
  `entity:nps_baseline`)
- _"In-app PMF survey runs continuously, 80% target cohort = paid users.
  Free-tier responses are out of scope, filter them out."_ (`pattern`,
  `domain:surveys`, `entity:pmf_targeting`)
- _"Open-text mentions of 'slow' baseline ~5%; above 15% is a perf
  regression signal worth bridging to product-analytics."_ (`pattern`,
  `domain:surveys`, `entity:slow_complaints_baseline`)
- _"Demo accounts (`@*-demo.example.com`) respond ~3x organic rate — skew
  rating distributions; filter."_ (`noise`, `domain:surveys`,
  `entity:demo_filter`)
- _"Survey 'why did you cancel' wording changed 2026-04-15 from 'Tell us
  why' to 'What didn't work for you'; score not directly comparable
  pre/post."_ (`pattern`, `domain:surveys`,
  `entity:cancel_survey_wording_change`)
- _"Open-text complaints about checkout step 3 cluster spotted
  2026-04-22, root-caused as missing trust signal, fixed in deploy
  abc123."_ (`addressed`, `domain:surveys`,
  `entity:checkout_step3_friction`)

These compound: by run #5, the scout knows the team's healthy NPS shape,
which surveys to interpret with which targeting context, which themes are
recurring vs novel, and which past complaints were already resolved.
