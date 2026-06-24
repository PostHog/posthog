import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi } from '../../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'
import { FacetConfig } from './facets'
import { logsFacetsLogic } from './logsFacetsLogic'

export interface FacetCountsLogicProps {
    id: string
}

/**
 * Per-facet values + counts, cross-filtered server-side: each facet's results reflect every active
 * filter except its own selection (see the backend's exclude_facet_field / exclude_resource_attribute /
 * exclude_attribute). Values come back ordered by count descending, keyed by facet key. Dynamic facets
 * (service, recent attribute facets) also pass a per-facet type-ahead search so they can match values
 * beyond the returned window.
 */
export const facetCountsLogic = kea<facetCountsLogicType>([
    props({ id: 'default' } as FacetCountsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'logs', 'frontend', 'components', 'LogsViewer', 'FacetRail', 'facetCountsLogic', key]),

    connect((props: FacetCountsLogicProps) => ({
        values: [
            logsViewerFiltersLogic({ id: props.id }),
            ['filters', 'utcDateRange', 'queryFilterGroup'],
            logsFacetsLogic({ id: props.id }),
            ['facets'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    actions({
        setFacetSearch: (facetKey: string, search: string) => ({ facetKey, search }),
    }),

    reducers({
        facetSearch: [
            {} as Record<string, string>,
            {
                setFacetSearch: (state, { facetKey, search }) => ({ ...state, [facetKey]: search }),
            },
        ],
    }),

    loaders(({ values }) => {
        const fetchValues = async (facet: FacetConfig): Promise<_LogFacetValueApi[]> => {
            if (!values.currentTeamId) {
                return []
            }
            const group = values.queryFilterGroup as UniversalFiltersGroup
            const filterGroup = ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ??
                []) as unknown as _LogPropertyFilterApi[]
            const { source } = facet
            const response = await logsFacetValuesCreate(String(values.currentTeamId), {
                query: {
                    facetField: source.type === 'column' ? source.column : undefined,
                    facetResourceAttribute: source.type === 'resourceAttribute' ? source.key : undefined,
                    facetAttribute: source.type === 'logAttribute' ? source.key : undefined,
                    dateRange: values.utcDateRange,
                    severityLevels: values.filters.severityLevels ?? [],
                    serviceNames: values.filters.serviceNames ?? [],
                    searchTerm: values.filters.searchTerm || undefined,
                    facetSearch: values.facetSearch[facet.key] || undefined,
                    filterGroup,
                },
            })
            return response.results
        }

        return {
            // Values + counts for every facet, keyed by facet key. The whole map is reloaded together
            // so the previous values persist (no flicker) until the fresh batch arrives.
            facetValues: [
                {} as Record<string, _LogFacetValueApi[]>,
                {
                    loadFacetValues: async (_: null, breakpoint) => {
                        await breakpoint(300)
                        const facets = values.facets
                        const entries = await Promise.all(
                            facets.map(async (facet) => [facet.key, await fetchValues(facet)] as const)
                        )
                        breakpoint()
                        return Object.fromEntries(entries)
                    },
                },
            ],
        }
    }),

    listeners(({ actions }) => ({
        setFacetSearch: () => actions.loadFacetValues(null),
    })),

    subscriptions(({ actions }) => {
        // Fires on mount (initial load) and on any change. We watch `filters` (severity, service,
        // search, date, user filterGroup), `queryFilterGroup` (which folds in pinnedFilters, e.g. the
        // person-tab distinct_id pin), and `facets` (recent facets appear as filters are used) so
        // values re-fetch when any of them change. The 300ms debounce in the loader collapses bursts.
        const reload = (): void => actions.loadFacetValues(null)
        return {
            filters: reload,
            queryFilterGroup: reload,
            facets: reload,
        }
    }),
])
