import type { QuotaProjection } from '../../utils/quotaProjection'

interface Props {
    projection: QuotaProjection
    /** Free-plan orgs run out of credits; everyone else hits a spend limit they chose. */
    onFreePlan: boolean
}

/**
 * A short quota line: red for a spend fact (exhausted or already over the limit), amber for a forecast.
 * A projection can only ever render as a forecast, never as a limit reached. Renders nothing when safe.
 */
export function QuotaStatusLine({ projection, onFreePlan }: Props): JSX.Element | null {
    const message = statusMessage(projection, onFreePlan)
    if (!message) {
        return null
    }
    // Facts are red; a forecast is amber, so "projected to be reached" never reads like a breach.
    const isFact = projection.exhausted || projection.usedPct >= 100
    return <span className={isFact ? 'text-danger' : 'text-warning'}>{message}</span>
}

function statusMessage(projection: QuotaProjection, onFreePlan: boolean): JSX.Element | string | null {
    if (projection.exhausted) {
        return onFreePlan ? 'Free credits used up' : 'Spend limit reached'
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
    return null
}
