import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { DateRange, InsightVizNode } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import type { errorTrackingBreakdownsLogicType } from './errorTrackingBreakdownsLogicType'

export interface ErrorTrackingBreakdownsLogicProps {
    id: string
}

export const errorTrackingBreakdownsLogic = kea<errorTrackingBreakdownsLogicType>([
    path(['products', 'error_tracking', 'components', 'Breakdowns', 'errorTrackingBreakdownsLogic']),
    props({} as ErrorTrackingBreakdownsLogicProps),
    key(({ id }: ErrorTrackingBreakdownsLogicProps) => id),
    connect({
        values: [breakdownFiltersLogic, ['dateRange', 'filterTestAccounts']],
    }),
    actions({
        setBreakdownProperty: (property: string) => ({ property }),
    }),
    reducers(({ props }) => ({
        breakdownProperty: [
            '$browser' as string,
            {
                setBreakdownProperty: (_, { property }) => property,
            },
        ],
        issueId: [props.id],
    })),
    selectors({
        breakdownQuery: [
            (s, p) => [s.breakdownProperty, s.dateRange, s.filterTestAccounts, p.id],
            (
                breakdownProperty: string,
                dateRange: DateRange,
                filterTestAccounts: boolean,
                issueId: string
            ): InsightVizNode | null => {
                if (!breakdownProperty) {
                    return null
                }

                return errorTrackingIssueBreakdownQuery({
                    breakdownProperty,
                    dateRange,
                    filterTestAccounts,
                    filterGroup: {
                        type: FilterLogicalOperator.And,
                        values: [{ type: FilterLogicalOperator.And, values: [] }],
                    },
                    issueId,
                })
            },
        ],
    }),
])
