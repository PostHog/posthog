# Tracing latency heatmap

- **Single sparkline endpoint** carries `sparklineBreakdownBy` + `heatmapIncludeQuantiles` (schema option A from the review) instead of a separate route, matching logs sparkline patterns and keeping one MCP tool surface.
- **Brush state** lives in `tracingFiltersLogic.selectedRegion` with explicit Zoom / BubbleUp actions (no auto-filter on brush end) so future iterations can deepen BubbleUp without rewiring chart state.
- **TSX `>` gotcha**: avoid `count > 0` inline inside JSX braces; hoist boolean conditions to variables above the `return` so `>` is not parsed as closing a tag.
- **Default chart mode**: when the URL has no `chart` query param, mode tracks `FEATURE_FLAGS.TRACING` (`tracing`): flag on → latency heatmap, off → volume by service. Explicit `chart=volume` / `chart=latency` always wins. `setFeatureFlags` listener reapplies the default when flags load async so first paint matches persisted/bootstrap flags.
- **Progressive heatmap load** (last hour then full range): not implemented; add if traces CH p95 stays high on wide ranges after measuring with the flag rolled out.
- **CH projection** for `(time, log2(duration), service)`: deferred until heatmap byte/time p95 exceeds the review threshold (~150ms / unacceptable cost); `TRACE_SPANS_HEATMAP_SETTINGS` caps bytes today.
- **Heatmap Y UI labels**: the toggle only changes **row order** (linear = ascending log₂ buckets → slower spans toward the top; log = reversed domain → slower toward the bottom). Labels say “Slow at top” / “Slow at bottom” instead of “Linear Y” / “Log Y”.
- **BubbleUp UX**: heatmap button uses `LemonButton` `tooltip`; modal title + table headers use `Tooltip` + `IconInfo` with copy centralized in `bubbleUpCopy.ts` so interpretation (lift, inset vs baseline) stays aligned with backend behavior.
