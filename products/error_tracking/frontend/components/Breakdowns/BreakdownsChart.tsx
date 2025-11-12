import { useValues } from 'kea'
import { useMemo } from 'react'

import { Query } from '~/queries/Query/Query'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'

export function BreakdownsChart(): JSX.Element {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { breakdownProperty, dateRange, filterTestAccounts } = useValues(breakdownFiltersLogic)

    const query = useMemo(
        () =>
            errorTrackingIssueBreakdownQuery({
                breakdownProperty,
                dateRange,
                filterTestAccounts,
                filterGroup: {
                    type: FilterLogicalOperator.And,
                    values: [{ type: FilterLogicalOperator.And, values: [] }],
                },
                issueId: issue?.id ?? '',
            }),
        [breakdownProperty, dateRange, filterTestAccounts, issue?.id]
    )

    if (!issue?.id) {
        return <></>
    }

    return (
        <div className="border rounded bg-surface-primary p-3">
            <Query query={query} context={{ ignoreActionsInSeriesLabels: true }} />
        </div>
    )
}
