import type { QuotaProjection } from '../../utils/quotaProjection'

interface Props {
    projection: QuotaProjection
    /** Free-plan orgs run out of credits; everyone else hits a spend limit they chose. */
    onFreePlan: boolean
}

/** Red warning when the allocation is exhausted or projected to overshoot; renders nothing otherwise. */
export function QuotaStatusLine({ projection, onFreePlan }: Props): JSX.Element | null {
    const message = statusMessage(projection, onFreePlan)
    return message ? <span className="text-danger">{message}</span> : null
}

function statusMessage(projection: QuotaProjection, onFreePlan: boolean): JSX.Element | string | null {
    if (projection.exhausted) {
        return onFreePlan ? 'Free credits used up' : 'Spend limit reached'
    }
    if (projection.status !== 'danger') {
        return null
    }
    // Over the displayed limit but not backend-exhausted (the startup cap before billing clamps):
    // "exceeded" states the spend fact without claiming scanning is paused.
    if (projection.usedPct >= 100) {
        return onFreePlan ? 'Free credits used up' : 'Monthly spend limit exceeded'
    }
    if (projection.capReachDate) {
        const date = <strong>{projection.capReachDate.format('MMMM D')}</strong>
        return onFreePlan ? (
            <>Free credits projected to run out on {date}</>
        ) : (
            <>Spend limit projected to be reached on {date}</>
        )
    }
    return onFreePlan ? 'Projected to use up the free credits' : 'Projected to exceed the monthly spend limit'
}
