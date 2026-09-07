import { IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { ClusterSummaryApi, RowShiftApi } from '../generated/api.schemas'

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
    if (value > 0 && value < PCT_DISPLAY_FLOOR) {
        return '<0.1%'
    }
    if (value < 1) {
        return `${value.toFixed(1)}%`
    }
    return `${Math.round(value)}%`
}

function pluralRows(count: number): string {
    return `${count} ${count === 1 ? 'row' : 'rows'}`
}

/**
 * How tall the movement is. The net height change when the page really grew
 * or shrank, and the larger side when inserts and deletes cancel out, because
 * the rows still moved even though the page kept its height.
 */
function shiftMagnitude(rowShift: RowShiftApi): number {
    const net = Math.abs(rowShift.inserted_rows - rowShift.deleted_rows)
    return net || Math.max(rowShift.inserted_rows, rowShift.deleted_rows)
}

/** Only name a position when there is one band, so it can't point at one of several. */
function shiftPosition(rowShift: RowShiftApi): string {
    return rowShift.bands.length === 1 ? ` at y=${rowShift.bands[0].y}` : ''
}

function formatResidual(value: number): string {
    if (value === 0) {
        return '0%'
    }
    return value < 0.01 ? `${value.toFixed(3)}%` : `${value.toFixed(2)}%`
}

function shiftChipLabel(rowShift: RowShiftApi): string {
    const net = rowShift.inserted_rows - rowShift.deleted_rows
    if (net === 0) {
        return `${pluralRows(shiftMagnitude(rowShift))} moved`
    }
    return `${net > 0 ? '+' : '-'}${pluralRows(Math.abs(net))}`
}

function absorbedShiftTooltip(rowShift: RowShiftApi): string {
    const where = shiftPosition(rowShift)
    let opening: string
    if (rowShift.deleted_rows === 0) {
        opening = `The page grew by ${pluralRows(rowShift.inserted_rows)}${where}.`
    } else if (rowShift.inserted_rows === 0) {
        opening = `The page shrank by ${pluralRows(rowShift.deleted_rows)}${where}.`
    } else {
        opening = `The page shifted by ${pluralRows(shiftMagnitude(rowShift))}${where}.`
    }
    return (
        `${opening} Rows below it moved, and after aligning them only ${formatResidual(rowShift.residual_percentage)} ` +
        `of pixels differ, so this run was absorbed as noise. Without alignment it would have read as ` +
        `${rowShift.raw_diff_percentage.toFixed(2)}% pixel diff.`
    )
}

function layoutShiftTooltip(rowShift: RowShiftApi): string {
    const parts: string[] = []
    if (rowShift.inserted_rows > 0) {
        parts.push(`${pluralRows(rowShift.inserted_rows)} added`)
    }
    if (rowShift.deleted_rows > 0) {
        parts.push(`${pluralRows(rowShift.deleted_rows)} removed`)
    }
    return (
        `${parts.join(' and ')}${shiftPosition(rowShift)}. Content in the matched rows changed by ` +
        `${formatResidual(rowShift.residual_percentage)} (residual).`
    )
}

/** Rows the aligner actually moved. Zero when the pair aligned with no shift at all. */
function shiftedRowCount(rowShift: RowShiftApi | null | undefined): number {
    return rowShift ? rowShift.inserted_rows + rowShift.deleted_rows : 0
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
    // The vertical shift the diff pipeline measured. Present on absorbed
    // snapshots too, which is the only signal those carry.
    row_shift?: RowShiftApi | null
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
    if (shiftedRowCount(snapshot.row_shift) > 0 && (kind === '' || kind === 'layout')) {
        return true
    }
    if (kind === 'pixel' || kind === '' || kind === 'layout') {
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
 * `pixel` shows a percentage pill. `structural` shows the pixel diff %
 * alongside a "Perceptible change" label — the % is real but low, and
 * the label explains why it's flagged. Both tiers use the same metric
 * (pixel diff %) so the overview can average across them.
 *
 * `layout` shows how many rows the page gained or lost. A snapshot with a
 * row shift and no kind was absorbed as noise, and gets a neutral chip so
 * the run still shows what moved.
 *
 * Returns null when there's nothing to show (no diff, no size mismatch,
 * no shift, or pre-migration legacy row with no kind and no percentage).
 */
export function SnapshotChangeBadge({ snapshot, size = 'default' }: ChangeBadgeProps): JSX.Element | null {
    const kind = snapshot.change_kind || ''
    const pct = snapshot.diff_percentage ?? null
    const rowShift = snapshot.row_shift ?? null
    const hasShift = !!rowShift && shiftedRowCount(rowShift) > 0
    const isCompact = size === 'small'
    // Smaller padding + non-pill corners on the filmstrip; the rounded-full
    // pill plus icon pair was too visually heavy stacked next to a thumbnail.
    const sizeClass = isCompact ? 'text-[10px] px-1 py-0' : 'text-[11px] px-2 py-0.5'
    const iconClass = isCompact ? 'w-2.5 h-2.5' : 'w-3.5 h-3.5'
    const radiusClass = isCompact ? 'rounded' : 'rounded-full'

    let kindChip: JSX.Element | null = null

    if (kind === 'structural') {
        const hasPct = pct != null
        const tooltip = hasPct
            ? `${pct.toFixed(2)}% of pixels differ, but the change is perceptually significant. Structural similarity analysis confirmed this is a real visual change.`
            : 'Few pixels differ, but the change is perceptually significant. Structural similarity analysis confirmed this is a real visual change.'
        kindChip = (
            <Tooltip title={tooltip}>
                <span
                    className={`shrink-0 inline-flex items-center gap-1 bg-primary-highlight font-medium text-primary leading-none ${radiusClass} ${sizeClass}`}
                >
                    {hasPct && <span className="font-mono tabular-nums">{formatPct(pct)}</span>}
                    {isCompact ? 'Perceptible' : 'Perceptible change'}
                </span>
            </Tooltip>
        )
    } else if (kind === 'layout' && hasShift) {
        kindChip = (
            <Tooltip title={layoutShiftTooltip(rowShift)}>
                <span
                    className={`shrink-0 inline-flex items-center gap-1 bg-warning-highlight/60 font-medium text-warning-dark leading-none ${radiusClass} ${sizeClass}`}
                >
                    <span className="font-mono tabular-nums">{shiftChipLabel(rowShift)}</span>
                    {!isCompact && 'Layout shift'}
                </span>
            </Tooltip>
        )
    } else if (kind === '' && hasShift) {
        // Absorbed as noise. Neutral, not warning: nothing here needs review,
        // the chip is only there so the run does not look like it saw nothing.
        const absorbedLabel = `${shiftMagnitude(rowShift)}px shift`
        kindChip = (
            <Tooltip title={absorbedShiftTooltip(rowShift)}>
                <span
                    className={`shrink-0 inline-flex items-center bg-bg-3000 font-medium text-muted-alt leading-none ${radiusClass} ${sizeClass}`}
                >
                    {isCompact ? absorbedLabel : `Absorbed ${absorbedLabel}`}
                </span>
            </Tooltip>
        )
    } else if ((kind === 'pixel' || kind === '' || kind === 'layout') && pct != null && pct >= PCT_DISPLAY_FLOOR) {
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
            const ssimClamped = Math.max(0, Math.min(1, snapshot.ssim_score))
            tooltipBits.push(`${((1 - ssimClamped) * 100).toFixed(1)}% perceptual diff`)
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
    // A shift already says the page changed height, and says it more
    // precisely, so the size chip would only repeat it in warning colors.
    const sizeChip =
        snapshot.size_mismatch && !hasShift ? (
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
