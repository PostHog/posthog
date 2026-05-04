import { IconPulse, IconWarning } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

import type { ClusterSummaryApi } from '../generated/api.schemas'

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
 * diff was below threshold), or `viewport_mismatch` (different image
 * dimensions, percentage numbers are dominated by padding and untrustworthy).
 *
 * Renders different copy per kind so users don't read every number against
 * the threshold they remember. Returns null when there's nothing to show
 * (no diff, or pre-migration legacy row with no kind and no percentage).
 */
export function SnapshotChangeBadge({ snapshot, size = 'default' }: ChangeBadgeProps): JSX.Element | null {
    const kind = snapshot.change_kind || ''
    const pct = snapshot.diff_percentage ?? null
    const sizeClass = size === 'small' ? 'text-[10px] px-1.5 py-0.5' : 'text-[11px] px-2 py-0.5'
    const iconClass = size === 'small' ? 'w-3 h-3' : 'w-3.5 h-3.5'

    if (kind === 'viewport_mismatch') {
        return (
            <Tooltip title="Baseline and current screenshots differ in dimensions. Diff numbers are dominated by padding and unreliable until the snapshots are captured at the same size.">
                <span
                    className={`shrink-0 inline-flex items-center gap-1 bg-danger/10 rounded-full font-medium text-danger leading-none ${sizeClass}`}
                >
                    <IconWarning className={iconClass} />
                    Viewport mismatch
                </span>
            </Tooltip>
        )
    }

    if (kind === 'structural') {
        const ssimText =
            snapshot.ssim_score != null
                ? `SSIM ${snapshot.ssim_score.toFixed(3)} — structurally different despite few pixels changing.`
                : 'Structural shift caught by SSIM despite few pixels changing.'
        return (
            <Tooltip
                title={`Layout shift. ${ssimText} Pixel-diff percentage isn't shown because it's below the classifier threshold and would mislead.`}
            >
                <span
                    className={`shrink-0 inline-flex items-center gap-1 bg-primary-highlight rounded-full font-medium text-primary leading-none ${sizeClass}`}
                >
                    <IconPulse className={iconClass} />
                    Layout shift
                </span>
            </Tooltip>
        )
    }

    // `pixel` (current pipeline) and legacy rows (no `change_kind` but a
    // populated `diff_percentage`) both render as the percentage pill —
    // it's a true pixel diff number in both cases.
    if ((kind === 'pixel' || kind === '') && pct != null && pct >= PCT_DISPLAY_FLOOR) {
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
                className={`shrink-0 inline-flex items-center gap-1 rounded-full font-mono tabular-nums leading-none ${sizeClass} ${
                    isHigh
                        ? 'bg-warning-highlight text-warning-dark font-semibold'
                        : 'bg-warning-highlight text-warning-dark'
                }`}
            >
                <IconPulse className={iconClass} />
                {formatPct(pct)}
            </span>
        )
        return tooltip ? <Tooltip title={tooltip}>{chip}</Tooltip> : chip
    }

    return null
}
