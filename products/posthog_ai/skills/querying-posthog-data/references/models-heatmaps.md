# Heatmaps

## Heatmap interactions (`heatmaps`)

Every click, rageclick, mouse move, and scroll-depth sample captured by the SDK when `heatmaps_opt_in` is on for the team.
This is a first-class HogQL table (no `system.` prefix). Coordinates are stored scaled _down_ by `scale_factor` (always 16) — **multiply** `x`/`y`/`viewport_*` by `scale_factor` to recover CSS pixels (e.g. `y * scale_factor`). Retained for 90 days.

### Columns

Column | Type | Nullable | Description
`session_id` | varchar | NOT NULL | Session the interaction belongs to (join to `session_recordings.session_id`)
`team_id` | integer | NOT NULL | Team this interaction belongs to
`distinct_id` | varchar | NOT NULL | Person who interacted
`timestamp` | DateTime64 | NOT NULL | When the interaction happened
`x` | integer | NOT NULL | Horizontal position, stored scaled down by `scale_factor` (multiply to get CSS px)
`y` | integer | NOT NULL | Vertical position, stored scaled down by `scale_factor` (multiply to get CSS px)
`scale_factor` | integer | NOT NULL | Factor the coordinates were divided by at ingestion (always 16); multiply stored values by it to recover CSS pixels
`viewport_width` | integer | NOT NULL | Viewport width, stored scaled down by `scale_factor` (multiply to get CSS px)
`viewport_height` | integer | NOT NULL | Viewport height, stored scaled down by `scale_factor` (multiply to get CSS px)
`pointer_target_fixed` | boolean | NOT NULL | Whether the clicked element is fixed-position
`current_url` | varchar | NOT NULL | Full URL of the page the interaction happened on
`type` | varchar | NOT NULL | `click`, `rageclick`, `mousemove`, or `scrolldepth`

### Example: top click hotspots on a page (last 7 days)

```sql
SELECT
    round(x / viewport_width, 2) AS rel_x,
    y * scale_factor AS client_y,
    count() AS clicks
FROM heatmaps
WHERE current_url = 'https://example.com/pricing'
  AND type = 'click'
  AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY rel_x, client_y
ORDER BY clicks DESC
LIMIT 20
```

### Example: rageclick volume by page

```sql
SELECT current_url, count() AS rageclicks
FROM heatmaps
WHERE type = 'rageclick' AND timestamp >= now() - INTERVAL 7 DAY
GROUP BY current_url
ORDER BY rageclicks DESC
LIMIT 20
```

### Important notes

- Heatmaps store coordinates, not element identity. To learn _what_ sits at a hotspot, cross-reference `$autocapture` events on the same `current_url` (their `elements_chain` / `$el_text` name the elements).
- `scrolldepth` rows encode reach down the page: `(y + viewport_height) * scale_factor` is how far the person scrolled.

## Saved heatmaps

Saved heatmaps (a pinned page URL plus rendered screenshots to overlay data on) are an operational catalog, not an analytics table — manage them through the MCP heatmap tools (`heatmaps-saved-list`, `heatmaps-saved-get`, `heatmaps-saved-create`, `heatmaps-saved-update`, `heatmaps-saved-regenerate`) rather than via SQL. The rendered screenshot itself isn't exposed over MCP; the user views it in the PostHog UI.
