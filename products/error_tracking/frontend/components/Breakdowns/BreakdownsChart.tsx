import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'

import { errorTrackingBreakdownsLogic } from './errorTrackingBreakdownsLogic'

export function BreakdownsChart(): JSX.Element {
    const { breakdownQuery } = useValues(errorTrackingBreakdownsLogic)

    return (
        <div className="border rounded bg-surface-primary p-3">
            <Query query={breakdownQuery} context={{ ignoreActionsInSeriesLabels: true }} />
        </div>
    )
}
