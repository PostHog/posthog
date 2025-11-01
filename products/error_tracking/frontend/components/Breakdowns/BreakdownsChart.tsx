import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'

export function BreakdownsChart(): JSX.Element {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { breakdownProperty, dateRange, filterTestAccounts } = useValues(breakdownFiltersLogic)

    if (!issue) {
        return <></>
    }

    const query = errorTrackingIssueBreakdownQuery({
        breakdownProperty,
        dateRange,
        filterTestAccounts,
        filterGroup: {
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: [] }],
        },
        issueId: issue.id,
    })

    return (
        <div className="border rounded bg-surface-primary p-3">
            <Query query={query} context={{ ignoreActionsInSeriesLabels: true }} />
        </div>
    )
}
