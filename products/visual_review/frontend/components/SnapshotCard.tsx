import { IconFlag, IconPulse, IconWarning } from '@posthog/icons'
import { LemonTag, Link } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'

import type { BaselineEntryApi } from '../generated/api.schemas'
import { parseArea, parseTheme } from '../lib/parseIdentifier'

// Drift is shown as a percentage with one decimal — anything less is sub-pixel
// noise and not actionable; anything more on a thumbnail-sized card is illegible.
function formatDriftPct(value: number): string {
    if (value >= 10) {
        return `${value.toFixed(0)}%`
    }
    return `${value.toFixed(1)}%`
}

// Anything below this rounds to "0.0%" via the formatter above, which would
// render a misleading "no drift" chip on a card that does have drift. Hide
// the chip entirely below this floor; the data is still in the API response
// for anyone who wants the exact number.
const DRIFT_DISPLAY_FLOOR_PCT = 0.05

// Crossing this threshold tints the drift chip in the warning palette so the
// eye lands on the loudest cards first. Picked for visual hierarchy, not
// derived from the backend classifier — pixel/SSIM thresholds in
// `diffing.py` are unrelated to this UI hook.
const DRIFT_WARNING_THRESHOLD_PCT = 1

// Mirrors `BASELINE_DRIFT_RECENT_RUN_COUNT` in
// `products/visual_review/backend/facade/contracts.py`. Keep in sync — the
// backend value drives `recent_drift_avg`, this constant drives the copy.
export const RECENT_DRIFT_WINDOW = 10

export function SnapshotCard({
    repoId,
    entry,
    thumbnailBasePath,
}: {
    repoId: string
    entry: BaselineEntryApi
    thumbnailBasePath: string | null
}): JSX.Element {
    const { theme } = parseTheme(entry.identifier)
    const area = parseArea(entry.identifier)
    const tolerateCount = entry.tolerate_count_30d
    const driftPct = entry.recent_drift_avg ?? 0
    const driftVisible = driftPct >= DRIFT_DISPLAY_FLOOR_PCT
    const driftLoud = driftPct >= DRIFT_WARNING_THRESHOLD_PCT
    // Only build the thumbnail URL when we know there's a thumbnail to fetch —
    // otherwise the endpoint 404s and browsers show the broken-image glyph.
    const thumbnailUrl =
        thumbnailBasePath && entry.thumbnail_hash
            ? `${thumbnailBasePath}/${encodeURIComponent(entry.identifier)}/`
            : null
    const href = urls.visualReviewSnapshotHistory(repoId, entry.run_type, entry.identifier)
    const hasMeta = driftVisible || tolerateCount > 0 || entry.baseline_change_count > 0

    return (
        <Link
            to={href}
            // Without an explicit border-color, Tailwind's `border` falls back
            // to `currentColor` — and Link sets `currentColor` to the primary
            // orange. That painted every card with an orange frame.
            className="border border-border rounded bg-bg-light overflow-hidden flex flex-col text-default hover:border-primary transition-colors"
            data-attr="visual-review-snapshot-card"
        >
            <div
                // Thumbnails are bounded by pixelhog at THUMB_WIDTH (200) ×
                // THUMB_HEIGHT (140), so we know the box can never overflow.
                // Fix the height to the cap and align top so taller content
                // anchors consistently across cards; shorter content lets
                // the bg-light (or bg-3000 for dark variants) show beneath.
                className={`relative h-[140px] flex items-start justify-center overflow-hidden border-b border-border ${
                    theme === 'dark' ? 'bg-bg-3000' : 'bg-bg-light'
                }`}
            >
                {thumbnailUrl ? (
                    <img
                        src={thumbnailUrl}
                        alt={entry.identifier}
                        loading="lazy"
                        decoding="async"
                        className="max-w-full max-h-full object-contain"
                    />
                ) : (
                    <span className="text-muted text-xs my-auto">No thumbnail</span>
                )}
                {/* Corner is reserved for severity-only signals: quarantine
                    means "broken, system stopped trusting this". Activity
                    metrics (tolerate / drift / baseline-change) live in the
                    meta row below where they can be compared on the same axis. */}
                {entry.is_quarantined && (
                    <div className="absolute top-1.5 right-1.5">
                        <Tooltip title="Currently quarantined — excluded from gating">
                            <span className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full text-white text-[10px] font-semibold leading-none bg-warning">
                                <IconWarning className="w-3 h-3" />
                            </span>
                        </Tooltip>
                    </div>
                )}
            </div>

            <div className="p-2 flex flex-col gap-1 min-w-0">
                <div className="font-mono text-xs truncate" title={entry.identifier}>
                    {entry.identifier}
                </div>
                <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
                    <LemonTag type="default" size="small">
                        {area}
                    </LemonTag>
                    {hasMeta && (
                        <div className="flex items-center gap-2 shrink-0 tabular-nums leading-none">
                            {driftVisible && (
                                <Tooltip
                                    title={`Average pixel drift over the last ${RECENT_DRIFT_WINDOW} default-branch runs: ${driftPct.toFixed(
                                        2
                                    )}%`}
                                >
                                    <span
                                        className={`inline-flex items-center gap-0.5 ${
                                            driftLoud ? 'text-warning-dark font-semibold' : ''
                                        }`}
                                    >
                                        <IconPulse className="w-3 h-3" />
                                        {formatDriftPct(driftPct)}
                                    </span>
                                </Tooltip>
                            )}
                            {tolerateCount > 0 && (
                                <Tooltip
                                    title={`Drift accepted ${tolerateCount} time${
                                        tolerateCount === 1 ? '' : 's'
                                    } in last 30 days (human or agent)`}
                                >
                                    <span className="inline-flex items-center gap-0.5">
                                        <IconFlag className="w-3 h-3" />
                                        {tolerateCount}
                                    </span>
                                </Tooltip>
                            )}
                            {entry.baseline_change_count > 0 && (
                                <Tooltip
                                    title={`Baseline updated ${entry.baseline_change_count} time${
                                        entry.baseline_change_count === 1 ? '' : 's'
                                    } since inception`}
                                >
                                    <span className="font-mono">↻ {entry.baseline_change_count}</span>
                                </Tooltip>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </Link>
    )
}
