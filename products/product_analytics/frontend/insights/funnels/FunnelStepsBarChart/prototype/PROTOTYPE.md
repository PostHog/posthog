# PROTOTYPE — funnel steps chart: two axes in compare mode

**Throwaway code. Do not ship. Do not merge to master.**

## The question

With "compare against" enabled, the funnel steps chart scales both periods against the **larger** period's entrants (`count / max(currentEntrants, previousEntrants)`).
So only the larger period's first step reads 100% on the single percent axis; the other period's first step reads e.g. 79%, with its missing volume left as a blank gap above.
Should the chart get a second value axis so each period gets its own 100% reference — and what should each axis show?

## The plan (one line)

Three variants + the live rendering of the funnel steps chart in compare mode, on the existing insight route, switchable via `?funnel_axes_variant=` — dev builds only, pure compare funnels only (no breakdown).

## How to run

1. `hogli start` (or `./bin/start`) and open any funnel insight in the Steps visualization.
2. Enable **Compare to previous period** (or any "compare against" option).
3. A floating `PROTOTYPE` pill appears bottom-center. Flip variants with its arrows, the `←`/`→` keys, or the URL: `?funnel_axes_variant=live|A|B|C`.

## The variants

| Key    | Name                      | Bars                                                                     | Axes                                                                                                                          |
| ------ | ------------------------- | ------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `live` | Shared axis (production)  | Volume-true: larger period fills 100%, smaller leaves a blank gap above  | One percent axis; only the larger period's first step reads 100%                                                              |
| `A`    | Twin percent axes         | Each period normalized to its own entrants — both first steps at the top | Left = this period's %, right = previous period's %, color-coded. Both read 0–100%; heights compare conversion rates directly |
| `B`    | Volume-true + second axis | Unchanged from `live`                                                    | Left = larger period's % (unchanged scale). Right = the smaller period's own 0–100% **compressed to its entry level**         |
| `C`    | Count axes                | As in `A` (each period = its own 100%)                                   | Both axes labeled in absolute user counts per period — the axis carries the volume difference the bars no longer show         |

What to judge:

- Does a second axis actually resolve the "the other period isn't 100%" confusion, or does it add more?
- `A`/`C` trade the volume-true bars for directly comparable conversion heights — is that gain worth losing the volume gap?
- `B` keeps today's bars but its right axis has ticks that don't align with the grid (two different scales) — classic dual-axis confusion?

## Known shortcuts (prototype constraints)

- Pure compare only; breakdown × compare falls back to the live rendering.
- Tooltip and StepLegend are untouched, so in `A`/`C` the bar heights use per-period normalization while the tooltip still reports production percentages.
- Axis title/tick styling is approximate (absolutely-positioned overlay labels, not the built-in axis renderer).

## Capturing the answer

When a variant wins: fold the decision into the real chart (`funnelStepsBarTransforms.ts` for the data shape; expose axis config through `FunnelChartConfig` in `@posthog/quill-charts` — the core `ChartConfig.yAxes` already supports per-series axes), then delete this folder and the graft in `FunnelStepsBarChart.tsx`. This branch stays as the primary source.
