import type { RowShiftApi } from '../generated/api.schemas'
import { describeBand } from '../lib/shiftCopy'

interface SnapshotShiftSummaryProps {
    rowShift: RowShiftApi
}

/**
 * Sidebar line naming where the page moved.
 *
 * Sits above the cluster panel because a shift explains the clusters below
 * it, and it renders on its own for an absorbed shift, where the residual is
 * too small to produce any cluster at all.
 */
export function SnapshotShiftSummary({ rowShift }: SnapshotShiftSummaryProps): JSX.Element | null {
    if (rowShift.bands.length === 0) {
        return null
    }
    return (
        <div>
            <h4 className="text-xs font-semibold text-muted mb-1">Row shift</h4>
            <div className="flex flex-col gap-0.5 text-[11px] text-muted tabular-nums">
                {rowShift.bands.map((band, i) => (
                    <span key={i}>{describeBand(band)}</span>
                ))}
            </div>
        </div>
    )
}
