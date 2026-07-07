---
name: assessing-heatmaps
description: "Assesses what a page's heatmap is telling you and recommends concrete changes. Pulls click / rageclick / scroll-depth data for a URL, names the hot elements by cross-referencing autocapture events on the same page, and can create a saved heatmap the user opens in PostHog, then summarizes the behavior and proposes improvements.\nTRIGGER when: user asks what a heatmap shows, why people aren't clicking something, where users rage-click, how far they scroll, what to change on a page based on heatmap/click data, or to 'analyze/assess/review the heatmap' for a URL.\nDO NOT TRIGGER when: the user only wants to create a saved heatmap screenshot with no analysis (use heatmaps-saved-create directly), or is asking about session replay in general (use investigating-replay)."
---

# Assessing heatmaps

A heatmap answers "where do people interact with this page?" — clicks, rage clicks, mouse movement, and how
far down they scroll. The data is pure geometry: `pointer_relative_x` (0..1 across the viewport), `pointer_y`
(absolute pixels down the page), and a count per spot. **It does not know what was clicked.** Turning
"lots of clicks at (0.5, 220)" into "lots of clicks on the Pricing nav link" is the whole job, and it comes
from cross-referencing autocapture on the same URL.

## Core principle: coordinates + meaning

You can't see the page — there is no screenshot in your context. A good assessment fuses two sources and
leans on autocapture to supply the layout/identity you can't see:

1. **Heatmap data** — where interactions land and how far people scroll (`heatmaps-list`).
2. **Autocapture** — what element sits under the hot spots, by element text / selector on the same page. This
   is what turns coordinates into meaning; without it you only have dots.

When the user wants to _see_ the heatmap, create a saved heatmap (Step 4) — that renders the page with the
data overlaid for them to open in PostHog. You reason from the data; they look at the picture.

## The flow

### Step 1: Pin the page and window

You need an exact `url_exact` (one page) or a `url_pattern` (regex, to aggregate across query strings). Confirm
the URL with the user if ambiguous. Default to the last 7 days; widen to 30 if volume is low. Heatmap data is
retained for 90 days.

### Step 2: Pull the data

Call `heatmaps-list` once per signal you care about (or query the `heatmaps` table directly via SQL — see the
querying-posthog-data skill, `models-heatmaps`):

- `type: "click"` — the primary "what draws attention" map.
- `type: "rageclick"` — repeated frustrated clicks. **The single strongest "something is broken or
  misleading" signal.** Any meaningful rageclick cluster deserves a callout.
- `type: "scrolldepth"` — how far people get. Use it to find the fold and spot CTAs that sit below where most
  people ever scroll.

Use `aggregation: "unique_visitors"` when you care about how many people (not how many clicks); `total_count`
exaggerates a few heavy clickers.

Click results come back **hottest-first** and are capped at `limit` (default 500). A busy page can have
thousands of distinct coordinates, so the default page plus the `fold` summary is almost always enough — the
hottest points are what analysis turns on. Don't ask for everything: raise `limit` or page with `offset` only
when you specifically need more, and check `has_more` to know the list was truncated. `scrolldepth` ignores
`limit` and always returns every bucket.

### Step 2b: Above the fold — read the `fold` summary

For the click types, `heatmaps-list` returns a `fold` object alongside `results`:

- `pct_below_fold` — share of non-fixed interactions that landed **below the user's initial viewport** (they
  had to scroll to reach them). This is one of the highest-value findings: content people actively click that
  sits below the fold is a prime candidate to move up.
- `below_fold_count` / `total_count` — the raw counts behind the percentage (fixed-position elements are
  excluded, since they're always on screen).
- `median_viewport_height` — the typical fold line in CSS pixels, to recommend against.

Report it concretely, e.g. "the fold is ~600px for most visitors, yet 35% of clicks land below it, so users
scroll before interacting — that content is a candidate for the first screen." **Segment by device** with
`viewport_width_min`/`viewport_width_max` (desktop and mobile have very different folds) and read `fold` per
band rather than blending them.

Need a distribution rather than a single percentage (e.g. clicks bucketed by how far below the fold)? Drop to
SQL on the raw `heatmaps` table, which has `y` and `viewport_height` in the same scaled units — see the
querying-posthog-data skill, `models-heatmaps`.

### Step 3: Name the hot elements (autocapture overlap)

For each notable cluster, find what's actually there. Query autocapture on the same URL — either via the
`exploring-autocapture-events` skill or directly:

```sql
SELECT properties.$el_text AS text, count() AS clicks
FROM events
WHERE event = '$autocapture'
  AND properties.$current_url = 'https://example.com/pricing'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY text
ORDER BY clicks DESC
LIMIT 25
```

`elements_chain` gives the selector/DOM path when you need to disambiguate two elements with the same text.
Match autocapture's top elements to the heatmap's hot coordinates: clicks concentrated on something that is
**not** a link or button (plain text, an image, a disabled control) is a classic "users expect this to be
clickable" finding.

### Step 4: Give the user a heatmap to look at (optional)

You can't see the page, but the user can. When a visual would help them follow your findings, create a saved
heatmap so they can open the rendered page with the data overlaid in PostHog:

1. `heatmaps-saved-create` with the page `url` (type defaults to `screenshot`). This enqueues a headless
   render — it is asynchronous. Pass `widths` matching the viewport band you analyzed in Step 2.
2. Poll `heatmaps-saved-get` (by the returned `short_id`) until `status` is `completed`, then tell the user
   it's ready to view in PostHog.

This is for the human's benefit — your own reasoning still comes from the Step 2 data and the Step 3
autocapture identity, not from the picture.

### Step 5: Drill into hotspots (when you need the "why")

For a surprising cluster, `heatmaps-events` returns the individual sessions behind specific `points`. Hand the
session IDs to the `investigating-replay` skill to watch what people actually did.

### Step 6: Summarize and recommend

Produce a short, concrete report:

- **What the heatmap shows** — top engaged elements, dead zones, scroll reach, and the above/below-the-fold
  click split (e.g. "viewport is ~600px for most visitors, yet 35% of clicks land below it").
- **Problems**, ranked by signal strength — rage-click clusters first, then clicks on non-interactive
  elements, then important CTAs sitting below the scroll cliff, then ignored primary actions.
- **Recommendations** tied to evidence — move/raise a CTA above the fold, make a clicked-but-dead element a
  real link, cut competing elements near a rage-click cluster, etc. Every recommendation should cite the
  signal it came from.

## Reading the signals

| Signal                             | Likely meaning                                                                    | Typical recommendation                                         |
| ---------------------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Rage clicks on an element          | Broken, slow, or looks-clickable-but-isn't                                        | Fix the handler, add feedback, or make it actually interactive |
| Many clicks on non-link text/image | Users expect it to be clickable                                                   | Make it a link/button, or remove the affordance                |
| Primary CTA gets few clicks        | Buried, low-contrast, or out-competed                                             | Raise it, increase contrast, reduce nearby noise               |
| Scroll cliff before key content    | Content/CTA is below where people stop                                            | Move it up or add a reason to scroll                           |
| High % of clicks below the fold    | Engaged content sits below the initial viewport — users scroll before interacting | Move the most-clicked elements onto the first screen           |
| Hot clicks on nav, cold body       | Page isn't delivering; people bail to nav                                         | Re-evaluate the page's core content                            |

## Gotchas

- **Heatmaps must be opted in** (`Team.heatmaps_opt_in`). If `heatmaps-list` returns nothing for a page that
  clearly gets traffic, capture may be off or the URL is wrong — check both before concluding "no
  engagement".
- **Coordinates are scaled** by a factor of 16 in storage; the API already returns CSS-pixel `pointer_y` and
  relative x, so use the API/tool values directly rather than the raw table columns.
- **You can't see the screenshot.** The saved-heatmap render is for the user to open in PostHog; don't claim
  to have looked at the page. Ground every layout claim in autocapture identity + coordinates, not vision.
- **Saved-heatmap rendering is async.** After `heatmaps-saved-create`, poll `heatmaps-saved-get` until
  `status` is `completed` before telling the user it's viewable. Only `screenshot`-type heatmaps render an
  image; `iframe` and `recording` types do not.
- **Mind the viewport.** A desktop click map and a mobile one are different pages' worth of behavior — filter
  with `viewport_width_min`/`viewport_width_max` rather than blending them.
