import type { QuotaProjection } from '../../utils/quotaProjection'

interface Props {
    projection: QuotaProjection
    /** Free-plan orgs run out of credits; everyone else hits a spend limit they chose. */
    onFreePlan: boolean
}

/** Red warning when the allocation is exhausted or projected to overshoot; renders nothing otherwise. */
export function QuotaStatusLine({ projection, onFreePlan }: Props): JSX.Element | null {
    if (projection.exhausted) {
        return <span className="text-danger">{onFreePlan ? 'Free credits used up' : 'Spend limit reached'}</span>
    }
    if (projection.status !== 'danger') {
        return null
    }
    if (projection.capReachDate) {
        const date = <strong>{projection.capReachDate.format('MMMM D')}</strong>
        return (
            <span className="text-danger">
                {onFreePlan ? (
                    <>Free credits projected to run out on {date}</>
                ) : (
                    <>Spend limit projected to be reached on {date}</>
                )}
            </span>
        )
    }
    return (
        <span className="text-danger">
            {onFreePlan ? 'Projected to use up the free credits' : 'Projected to exceed the monthly spend limit'}
        </span>
    )
}
