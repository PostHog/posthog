import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { FilterBar, FilterBarSortOption, SortDirection } from 'lib/components/FilterBar/FilterBar'

import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import { issueFiltersLogic } from 'products/error_tracking/frontend/components/IssueFilters/issueFiltersLogic'
import {
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'
import { issuesDataNodeLogic } from 'products/error_tracking/frontend/logics/issuesDataNodeLogic'

import { errorTrackingSceneLogic } from '../../errorTrackingSceneLogic'
import { useErrorTrackingFilterPicker } from './errorTrackingFilterPicker'
import { insightProps } from './IssuesList'

const SORT_OPTIONS: FilterBarSortOption[] = Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({ value, label }))

export function IssuesFilters(): JSX.Element {
    const { dateRange, filterGroup } = useValues(issueFiltersLogic)
    const { setDateRange, setFilterGroup } = useActions(issueFiltersLogic)
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)
    const { query } = useValues(errorTrackingSceneLogic)
    const issueDataNodeLogicProps = useMemo(
        () => ({ key: insightVizDataNodeKey(insightProps), query: query.source }),
        [query.source]
    )
    const { responseLoading } = useValues(issuesDataNodeLogic(issueDataNodeLogicProps))
    const { reloadData, cancelQuery } = useActions(issuesDataNodeLogic(issueDataNodeLogicProps))
    const innerFilterGroup = filterGroup.values[0] as UniversalFiltersGroup
    const { pickerRootNodes, pickerTokens } = useErrorTrackingFilterPicker({
        filterGroup: innerFilterGroup,
        onFilterChange: (group) => setFilterGroup({ type: FilterLogicalOperator.And, values: [group] }),
    })

    return (
        <FilterBar
            pickerRootNodes={pickerRootNodes}
            pickerTokens={pickerTokens}
            dateFrom={dateRange?.date_from ?? null}
            dateTo={dateRange?.date_to ?? null}
            onDateChange={(date_from, date_to) => setDateRange({ date_from, date_to })}
            sortOptions={SORT_OPTIONS}
            sortValue={orderBy}
            sortDirection={orderDirection as SortDirection}
            onSortChange={(value, direction) => {
                setOrderBy(value as typeof orderBy)
                setOrderDirection(direction as typeof orderDirection)
            }}
            onReload={() => {
                if (responseLoading) {
                    cancelQuery()
                } else {
                    reloadData()
                }
            }}
            reloadLoading={responseLoading}
        />
    )
}
