import MaxTool from 'scenes/max/MaxTool'
import { errorTrackingSceneLogic } from '../errorTrackingSceneLogic'
import { errorFiltersLogic } from './ErrorFilters/errorFiltersLogic'
import { issueQueryOptionsLogic } from './IssueQueryOptions/issueQueryOptionsLogic'
import { useActions, useValues } from 'kea'
import { ErrorTrackingSceneToolOutput } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import { taxonomicFilterLogicKey, taxonomicGroupTypes } from './ErrorFilters/FilterGroup'

function updateFilterGroup(
    removedFilterIndexes: number[] | undefined,
    newFilters: any[] | undefined,
    filterGroup: UniversalFiltersGroup
): UniversalFiltersGroup | null {
    if (!(newFilters && newFilters.length > 0) && !(removedFilterIndexes && removedFilterIndexes.length > 0)) {
        return null
    }

    const firstValue = filterGroup.values[0]
    let firstGroup: UniversalFiltersGroup

    if (firstValue && 'values' in firstValue) {
        firstGroup = firstValue
    } else {
        firstGroup = {
            type: FilterLogicalOperator.And,
            values: firstValue ? [firstValue] : [],
        }
    }

    let updatedValues = [...firstGroup.values]

    // Remove filters by index (largest index first to avoid shifting)
    if (removedFilterIndexes && removedFilterIndexes.length > 0) {
        const sortedIndexes = [...removedFilterIndexes].sort((a, b) => b - a)
        for (const index of sortedIndexes) {
            if (index >= 0 && index < updatedValues.length) {
                updatedValues.splice(index, 1)
            }
        }
    }

    // Add new filters
    if (newFilters && newFilters.length > 0) {
        updatedValues.push(...newFilters)
    }

    return {
        ...filterGroup,
        values: [
            {
                ...firstGroup,
                values: updatedValues,
            },
            ...filterGroup.values.slice(1),
        ],
    }
}

export function ErrorTrackingSceneTool(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)
    const { setDateRange, setFilterGroup, setFilterTestAccounts } = useActions(errorFiltersLogic)
    const { setOrderBy, setOrderDirection, setStatus } = useActions(issueQueryOptionsLogic)
    const { filterGroup } = useValues(errorFiltersLogic)
    const { setSearchQuery } = useActions(
        taxonomicFilterLogic({
            taxonomicFilterLogicKey: taxonomicFilterLogicKey,
            taxonomicGroupTypes: taxonomicGroupTypes,
        })
    )

    const callback = (update: ErrorTrackingSceneToolOutput): void => {
        if (update.orderBy) {
            setOrderBy(update.orderBy)
        }
        if (update.orderDirection) {
            setOrderDirection(update.orderDirection)
        }
        if (update.status) {
            setStatus(update.status)
        }
        if (update.searchQuery) {
            setSearchQuery(update.searchQuery)
        }
        if (update.dateRange) {
            setDateRange(update.dateRange)
        }
        if (update.filterTestAccounts !== undefined) {
            setFilterTestAccounts(update.filterTestAccounts)
        }

        // Handle newFilters and removedFilterIndexes - modify first group of existing filter structure
        const updatedFilterGroup = updateFilterGroup(update.removedFilterIndexes, update.newFilters, filterGroup)
        if (updatedFilterGroup) {
            setFilterGroup(updatedFilterGroup)
        }
    }

    return (
        <MaxTool
            name="search_error_tracking_issues"
            displayName="Filter issues"
            description="Max can search for issues by message, file name, event properties, or stack trace."
            context={{
                current_query: query,
            }}
            callback={(toolOutput: ErrorTrackingSceneToolOutput) => {
                callback(toolOutput)
            }}
            suggestions={[]}
            introOverride={{
                headline: 'What kind of issues are you looking for?',
                description: 'Search by message, file name, event properties, or stack trace.',
            }}
            className="hidden"
        >
            <div className="relative" />
        </MaxTool>
    )
}
