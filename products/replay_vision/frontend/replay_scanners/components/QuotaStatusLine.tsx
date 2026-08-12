import type { QuotaProjection } from '../../utils/quotaProjection'

interface Props {
    projection: QuotaProjection
    /** Free-plan orgs run out of credits; everyone else hits a spend limit they chose. */
    onFreePlan: boolean
    /**
     * The projection includes a scanner that isn't running, so the overshoot is conditional on enabling it.
     * Only the forward-looking messages change mood; spend already on the clock stays stated as fact.
     */
    draft?: boolean
}

/** Red warning when the allocation is exhausted or projected to overshoot; renders nothing otherwise. */
export function QuotaStatusLine({ projection, onFreePlan, draft = false }: Props): JSX.Element | null {
    const message = statusMessage(projection, onFreePlan, draft)
    return message ? <span className="text-danger">{message}</span> : null
}

function statusMessage(projection: QuotaProjection, onFreePlan: boolean, draft: boolean): JSX.Element | string | null {
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
        if (draft) {
            return onFreePlan ? (
                <>Would use up your free credits on {date}</>
            ) : (
                <>Would reach your spend limit on {date}</>
            )
        }
        return onFreePlan ? (
            <>Free credits projected to run out on {date}</>
        ) : (
            <>Spend limit projected to be reached on {date}</>
        )
    }
    if (draft) {
        return onFreePlan ? 'Would use up your free credits' : 'Would exceed the monthly spend limit'
    }
    return onFreePlan ? 'Projected to use up the free credits' : 'Projected to exceed the monthly spend limit'
}
