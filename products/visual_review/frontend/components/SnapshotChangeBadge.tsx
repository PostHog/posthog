import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { ClusterSummaryApi } from '../generated/api.schemas'

// IconPulse is intentionally NOT used here. The "pulse" icon reads as
// "average drift / activity over time" and only makes sense in the
// snapshots overview where we surface aggregated drift. On a single
// snapshot's diff result it overstates a one-off measurement and the
// filmstrip got crowded with two icon-bearing chips per card. See
// SnapshotCard / VisualReviewSnapshotOverviewScene for the avg-drift
// usage we kept.

// Display floor mirrors `DRIFT_DISPLAY_FLOOR_PCT` on the overview card —
// values below this would round to "0.0%" via the formatter and look like
// "no change" on a card that actually has change.
const PCT_DISPLAY_FLOOR = 0.05

// Crossing this tints the chip warning. Picked for visual hierarchy, not
// derived from any backend classifier threshold.
const PCT_WARNING_THRESHOLD = 5

function formatPct(value: number): string {
    if (value < 1) {
        return `${value.toFixed(1)}%`
    }
    return `${Math.round(value)}%`
}

type ChangeBadgeSnapshot = {
    change_kind?: string | null
    diff_percentage?: number | null
    ssim_score?: number | null
    // Optional — history entries don't carry cluster info; only the full
    // snapshot DTO does. The badge renders fine without it.
    cluster_summary?: ClusterSummaryApi | null
    // Sizes differed between baseline and current. Renders an extra chip
    // alongside the kind chip; doesn't replace it (a snapshot can have a
    // different viewport AND a real content change).
    size_mismatch?: boolean | null
}

/**
 * Mirrors the render rules below — true when the badge will render
 * something. Callers should gate parent-level layout (separators,
 * "Change" rows, hasDiff badges) on this rather than rolling their
 * own predicate, otherwise sub-floor/legacy snapshots leave empty
 * UI shells when the badge ends up returning null.
 */
export function hasSnapshotChangeBadge(snapshot: ChangeBadgeSnapshot): boolean {
    if (snapshot.size_mismatch) {
        return true
    }
    const kind = snapshot.change_kind || ''
    if (kind === 'structural') {
        return true
    }
    if (kind === 'pixel' || kind === '') {
        const pct = snapshot.diff_percentage ?? null
        if (pct != null && pct >= PCT_DISPLAY_FLOOR) {
            return true
        }
    }
    return false
}

type ChangeBadgeProps = {
    snapshot: ChangeBadgeSnapshot
    size?: 'small' | 'default'
}

/**
 * Categorical chip describing the *kind* of change in a snapshot.
 *
 * The diff pipeline classifies into one of: `pixel` (a chunk of pixels
 * visibly differ), `structural` (SSIM caught a layout shift while pixel
 * diff was below threshold). Size-mismatch is *not* a kind — it composes
 * with whichever kind the classifier picked, so when set it renders as
 * an additional chip next to the main one.
 *
 * Returns null when there's nothing to show (no diff, no size mismatch,
 * or pre-migration legacy row with no kind and no percentage).
 */
export function SnapshotChangeBadge({ snapshot, size = 'default' }: ChangeBadgeProps): JSX.Element | null {
    const kind = snapshot.change_kind || ''
    const pct = snapshot.diff_percentage ?? null
    const isCompact = size === 'small'
    // Smaller padding + non-pill corners on the filmstrip; the rounded-full
    // pill plus icon pair was too visually heavy stacked next to a thumbnail.
    const sizeClass = isCompact ? 'text-[10px] px-1 py-0' : 'text-[11px] px-2 py-0.5'
    const iconClass = isCompact ? 'w-2.5 h-2.5' : 'w-3.5 h-3.5'
    const radiusClass = isCompact ? 'rounded' : 'rounded-full'

    let kindChip: JSX.Element | null = null

    if (kind === 'structural') {
        const ssimText =
            snapshot.ssim_score != null
                ? `SSIM ${snapshot.ssim_score.toFixed(3)} — structurally different despite few pixels changing.`
                : 'Structural shift caught by SSIM despite few pixels changing.'
        kindChip = (
            <Tooltip
                title={`Layout shift. ${ssimText} Pixel-diff percentage isn't shown because it's below the classifier threshold and would mislead.`}
            >
                <span
                    className={`shrink-0 inline-flex items-center bg-primary-highlight font-medium text-primary leading-none ${radiusClass} ${sizeClass}`}
                >
                    {isCompact ? 'Shift' : 'Layout shift'}
                </span>
            </Tooltip>
        )
    } else if ((kind === 'pixel' || kind === '') && pct != null && pct >= PCT_DISPLAY_FLOOR) {
        // `pixel` (current pipeline) and legacy rows (no `change_kind`
        // but a populated `diff_percentage`) both render as the
        // percentage pill — it's a true pixel diff number in both cases.
        const isHigh = pct > PCT_WARNING_THRESHOLD
        const tooltipBits: string[] = []
        if (snapshot.cluster_summary && snapshot.cluster_summary.total > 0) {
            const t = snapshot.cluster_summary.total
            tooltipBits.push(`${t} ${t === 1 ? 'region' : 'regions'} affected`)
        }
        if (snapshot.ssim_score != null) {
            tooltipBits.push(`SSIM ${snapshot.ssim_score.toFixed(3)}`)
        }
        const tooltip = tooltipBits.length ? `${pct.toFixed(2)}% pixel diff. ${tooltipBits.join(' · ')}.` : null
        const chip = (
            <span
                className={`shrink-0 inline-flex items-center font-mono tabular-nums leading-none ${radiusClass} ${sizeClass} ${
                    isHigh
                        ? 'bg-warning-highlight text-warning-dark font-semibold'
                        : 'bg-warning-highlight/60 text-warning-dark'
                }`}
            >
                {formatPct(pct)}
            </span>
        )
        kindChip = tooltip ? <Tooltip title={tooltip}>{chip}</Tooltip> : chip
    }

    // Size mismatch is secondary info — render the full chip on the
    // verbose surface (sidebar) and an icon-only badge in the filmstrip
    // so two side-by-side chips don't crowd the thumbnail.
    const sizeChipTooltip =
        'Baseline and current screenshots had different dimensions. Pixelhog padded to the larger size before computing the diff, so metrics are still meaningful — they just include the new content area as part of the change.'
    const sizeChip = snapshot.size_mismatch ? (
        <Tooltip title={sizeChipTooltip}>
            <span
                className={`shrink-0 inline-flex items-center bg-warning-highlight font-medium text-warning-dark leading-none ${radiusClass} ${
                    isCompact ? 'p-0.5' : `gap-1 ${sizeClass}`
                }`}
            >
                <IconWarning className={iconClass} />
                {!isCompact && 'Size changed'}
            </span>
        </Tooltip>
    ) : null

    if (!kindChip && !sizeChip) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-1">
            {kindChip}
            {sizeChip}
        </span>
    )
}
