import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'

import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import MaxTool from 'scenes/max/MaxTool'

import { ErrorTrackingIssueFilteringToolOutput } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator, UniversalFiltersGroup } from '~/types'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'
import type { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { errorTrackingSceneLogic } from '../scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { TAXONOMIC_FILTER_LOGIC_KEY, TAXONOMIC_GROUP_TYPES } from './IssueFilters/consts'
import { issueFiltersLogic } from './IssueFilters/issueFiltersLogic'
import { isValidOrderBy, issueQueryOptionsLogic } from './IssueQueryOptions/issueQueryOptionsLogic'

// Static instruction rendered into the trusted context block — never interpolate user or ingested data.
const ISSUES_QUERY_TOOL_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The user has the error tracking issue list open. When you call query-error-tracking-issues-list, the filters ' +
        'from your query (filter group, status, date range, search, ordering, assignee) are also applied to the open ' +
        'page, so the user sees matching issues both in this chat and on screen.',
}

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

export function ErrorTrackingIssueFilteringTool(): JSX.Element {
    const { query } = useValues(errorTrackingSceneLogic)
    const { setDateRange, setFilterGroup, setFilterTestAccounts } = useActions(issueFiltersLogic)
    const { setAssignee, setOrderBy, setOrderDirection, setStatus } = useActions(issueQueryOptionsLogic)
    const { filterGroup } = useValues(issueFiltersLogic)
    const { setSearchQuery } = useActions(
        taxonomicFilterLogic({
            taxonomicFilterLogicKey: TAXONOMIC_FILTER_LOGIC_KEY,
            taxonomicGroupTypes: TAXONOMIC_GROUP_TYPES,
        })
    )

    useAttachedContext([
        { type: 'error_tracking_query', value: JSON.stringify(query), label: 'Current filters' },
        ISSUES_QUERY_TOOL_CONTEXT_ITEM,
    ])

    const callback = (update: ErrorTrackingIssueFilteringToolOutput): void => {
        if (update.orderBy && isValidOrderBy(update.orderBy)) {
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

    // The headless query tool's call input mirrored onto the open page. Unlike the incremental MaxTool
    // patch above, the input is a complete query: every field is applied, with omitted fields set to the
    // backend's request-serializer defaults so the page shows the same results the tool returned. The
    // args are raw agent-sent JSON (never zod-validated), so fields are coerced and type/operator are
    // defaulted. personId and release have no representation in the issue-filters UI;
    // limit/offset/volumeResolution are scene-managed presentation options.
    const applyIssuesListQuery = (input: Record<string, any>): void => {
        setOrderBy(input.orderBy || 'occurrences')
        setOrderDirection(input.orderDirection === 'ASC' ? 'ASC' : 'DESC')
        setStatus(input.status || 'active')
        setAssignee(input.assignee ?? null)
        setDateRange(input.dateRange ?? { date_from: '-7d', date_to: null })
        setFilterTestAccounts(input.filterTestAccounts === undefined ? true : !!input.filterTestAccounts)

        // user/filePath fold into the free-text search, mirroring the backend's build_search_query.
        // An empty result clears the page's search — the query ran without a search constraint.
        const search = [input.searchQuery, input.user, input.filePath]
            .filter((s): s is string => typeof s === 'string' && s.length > 0)
            .join(' ')
        setSearchQuery(search)

        const flat: UniversalFiltersGroup['values'] = (Array.isArray(input.filterGroup) ? input.filterGroup : []).map(
            (f: Record<string, any>) => ({
                ...f,
                type: f.type || PropertyFilterType.Event,
                operator: f.operator || PropertyOperator.Exact,
            })
        )
        // library/fingerprint accept a string or a string list — mirror the backend's as_list.
        if (input.library) {
            flat.push({
                type: PropertyFilterType.Event,
                key: '$lib',
                operator: PropertyOperator.Exact,
                value: Array.isArray(input.library) ? input.library : [input.library],
            })
        }
        if (input.fingerprint) {
            flat.push({
                type: PropertyFilterType.Event,
                key: '$exception_fingerprint',
                operator: PropertyOperator.Exact,
                value: Array.isArray(input.fingerprint) ? input.fingerprint : [input.fingerprint],
            })
        }
        if (input.url) {
            flat.push({
                type: PropertyFilterType.Event,
                key: '$current_url',
                operator: PropertyOperator.IContains,
                value: input.url,
            })
        }
        // An empty group resets the page's filters (the logic falls back to its default group).
        setFilterGroup({
            type: FilterLogicalOperator.And,
            values: [{ type: FilterLogicalOperator.And, values: flat }],
        })
    }

    useMcpToolApplyBack({
        tools: ['query-error-tracking-issues-list'],
        targetKey: 'error-tracking-issues',
        onApply: (_event, { innerInput }) => {
            if (!innerInput) {
                return
            }
            applyIssuesListQuery(innerInput)
        },
    })

    return (
        <MaxTool
            identifier="filter_error_tracking_issues"
            context={{ current_query: query }}
            contextDescription={{
                text: 'Current filters',
                icon: <IconFilter />,
            }}
            callback={(toolOutput: ErrorTrackingIssueFilteringToolOutput) => {
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
