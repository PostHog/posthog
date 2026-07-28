# Product analytics

Insights over captured events: trends, funnels, retention, paths.
The terms below currently cover paths v2; other clusters join as they crystallize.

## Language

### Paths v2

**Journey**:
One person's consecutive sequence of path items.
In open mode a person's events split into journeys at every inactivity gap longer than gap G, so one person can have many journeys in a date range.
_Avoid_: session, trail

**Path item**:
The identity of a node: a step source plus its label value, after path cleaning.
_Avoid_: node name, page

**Step source**:
An event plus an optional naming property that defines what can appear as path items (for example `$pageview` named by cleaned URL path).
_Avoid_: bucket, event type

**Open mode**:
The zero-setup chart mode: no anchor, journeys split on gap G.
_Avoid_: default mode, explore mode

**Anchored mode**:
The chart mode built around an anchor with a single window W.
Each person contributes exactly one sequence, so every displayed segment equals a plain funnel.
_Avoid_: funnel mode, start/end mode

**Anchor**:
The start or end point (later, a funnel step) an anchored chart is built around.
_Avoid_: start point, end point (as standalone terms)

**Gap G**:
Open mode's inactivity threshold that splits a person's events into journeys; defaults to 30 minutes.
_Avoid_: session timeout, window

**Window W**:
Anchored mode's single conversion window, anchored at the anchor; the same window the emitted funnel uses.
Defaults to 30 minutes.
_Avoid_: gap, windowInterval

**Edge**:
A single displayed transition between two adjacent nodes; the two-step segment.
_Avoid_: link, arrow

**Segment**:
A contiguous run of steps in a displayed path; the unit "view as funnel" converts.
_Avoid_: sub-path, flow

**Edge contract**:
The equality promise: a displayed edge equals a two-step item-strict funnel with window G over the same range; anchored mode extends it to segments of any depth with window W.
_Avoid_: parity, consistency guarantee

**Item-strict**:
Funnel strictness relative to the path-item universe: steps must be consecutive among included items, while events outside the universe are ignored.
_Avoid_: strict

**Converter**:
The single canonical translation from a segment to the funnel that reproduces its numbers exactly.
_Avoid_: view-as-funnel logic, query builder

**Collapse**:
Merging immediate repeats of the same path item within a journey; on by default.
_Avoid_: dedupe

**Unique-actor counting**:
Every displayed number counts each person at most once per element.
Sums across elements are not promised to reconcile (no flow conservation in open mode).
_Avoid_: totals, hits, event counts

**Drop-off**:
Unique people whose journey ends at a given step; shown as a per-column row.
_Avoid_: exit, abandonment

**Other row**:
The per-step bucket holding path items beyond the top rows per step; closed, drill-down only.
_Avoid_: overflow, rest

**Path cleaning**:
The rule set that rewrites raw labels (mostly URL paths) before they become path items; applied identically when converting a segment to a funnel.
Paths v2 consumes the rules; managing them belongs to web analytics.
_Avoid_: URL normalization

**Journey grid**:
The v2 chart: one column per step, a few rows per column, ribbons between them.
_Avoid_: sankey, flow chart
