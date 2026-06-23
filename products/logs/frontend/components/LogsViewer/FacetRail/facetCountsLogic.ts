import { connect, kea, key, path, props } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi } from '../../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'

export interface FacetCountsLogicProps {
    id: string
}

type FacetField = 'severity_text' | 'service_name'

function toCountMap(results: _LogFacetValueApi[]): Record<string, number> {
    return Object.fromEntries(results.map((r) => [r.value, r.count]))
}

/**
 * Per-facet value counts, cross-filtered server-side: each facet's counts reflect every active
 * filter except its own selection. Refetches whenever the filters change.
 */
export const facetCountsLogic = kea<facetCountsLogicType>([
    props({ id: 'default' } as FacetCountsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FacetRail', 'facetCountsLogic', key]),

    connect((props: FacetCountsLogicProps) => ({
        values: [
            logsViewerFiltersLogic({ id: props.id }),
            ['filters', 'utcDateRange', 'queryFilterGroup'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    loaders(({ values }) => {
        const fetchCounts = async (facetField: FacetField): Promise<Record<string, number>> => {
            if (!values.currentTeamId) {
                return {}
            }
            const group = values.queryFilterGroup as UniversalFiltersGroup
            const filterGroup = ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ??
                []) as unknown as _LogPropertyFilterApi[]
            const response = await logsFacetValuesCreate(String(values.currentTeamId), {
                query: {
                    facetField,
                    dateRange: values.utcDateRange,
                    severityLevels: values.filters.severityLevels ?? [],
                    serviceNames: values.filters.serviceNames ?? [],
                    searchTerm: values.filters.searchTerm || undefined,
                    filterGroup,
                },
            })
            return toCountMap(response.results)
        }

        return {
            levelCounts: [
                {} as Record<string, number>,
                {
                    loadLevelCounts: async (_: null, breakpoint) => {
                        await breakpoint(300)
                        const counts = await fetchCounts('severity_text')
                        breakpoint()
                        return counts
                    },
                },
            ],
            serviceCounts: [
                {} as Record<string, number>,
                {
                    loadServiceCounts: async (_: null, breakpoint) => {
                        await breakpoint(300)
                        const counts = await fetchCounts('service_name')
                        breakpoint()
                        return counts
                    },
                },
            ],
        }
    }),

    subscriptions(({ actions }) => {
        // Fires on mount (initial load) and on any change. We watch both `filters` (severity,
        // service, search, date, user filterGroup) and `queryFilterGroup` (which folds in
        // pinnedFilters, e.g. the person-tab distinct_id pin) so counts re-fetch when the pinned
        // scope changes too. `filterGroup` feeds both, so a normal edit fires both — the 300ms
        // debounce in each loader collapses that into one request.
        const reload = (): void => {
            actions.loadLevelCounts(null)
            actions.loadServiceCounts(null)
        }
        return {
            filters: reload,
            queryFilterGroup: reload,
        }
    }),
])
