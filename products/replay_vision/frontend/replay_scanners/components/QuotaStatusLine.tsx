import type { QuotaProjection } from '../../utils/quotaProjection'

/** Red warning when the spend limit is exhausted, exceeded, or projected to overshoot; renders nothing otherwise. */
export function QuotaStatusLine({ projection }: { projection: QuotaProjection }): JSX.Element | null {
    if (projection.exhausted) {
        return <span className="text-danger">Spend limit reached</span>
    }
    if (projection.status !== 'danger') {
        return null
    }
    // Over the displayed limit but not backend-exhausted (the startup cap before billing clamps):
    // "exceeded" states the spend fact without claiming scanning is paused.
    if (projection.usedPct >= 100) {
        return <span className="text-danger">Monthly spend limit exceeded</span>
    }
    return projection.capReachDate ? (
        <span className="text-danger">
            Spend limit projected to be reached on <strong>{projection.capReachDate.format('MMMM D')}</strong>
        </span>
    ) : (
        <span className="text-danger">Projected to exceed the monthly spend limit</span>
    )
}
