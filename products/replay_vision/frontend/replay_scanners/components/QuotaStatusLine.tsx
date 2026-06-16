import type { QuotaProjection } from '../../utils/quotaProjection'

/** Red warning when the quota is exhausted or projected to overshoot; renders nothing otherwise. */
export function QuotaStatusLine({ projection }: { projection: QuotaProjection }): JSX.Element | null {
    if (projection.exhausted) {
        return <span className="text-danger">Quota exhausted</span>
    }
    if (projection.status !== 'danger') {
        return null
    }
    return projection.capReachDate ? (
        <span className="text-danger">
            Quota projected to run out on <strong>{projection.capReachDate.format('MMMM D')}</strong>
        </span>
    ) : (
        <span className="text-danger">Projected to exceed the monthly quota</span>
    )
}
