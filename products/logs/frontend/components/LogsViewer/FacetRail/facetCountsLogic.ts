import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesMultiCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi, _LogsFacetSpecApi } from '../../../generated/api.schemas'
import { facetCountsLogicType } from './facetCountsLogicType'
import { FacetConfig } from './facets'
import { logsFacetsLogic } from './logsFacetsLogic'

export interface FacetCountsLogicProps {
    id: string
}

function facetSpec(facet: FacetConfig, search: string | undefined): _LogsFacetSpecApi {
    const { source } = facet
    return {
        key: facet.key,
        facetField: source.type === 'column' ? source.column : undefined,
        facetResourceAttribute: source.type === 'resourceAttribute' ? source.key : undefined,
        facetAttribute: source.type === 'logAttribute' ? source.key : undefined,
        facetSearch: search || undefined,
    }
}

/**
 * Values + counts for every facet, fetched in a single request and cross-filtered server-side: each
 * facet's results reflect every active filter except its own selection (see the backend's exclude_*).
 * Values come back ordered by count descending and are bucketed here by facet key. Dynamic facets
 * (service, recent attribute facets) also pass a per-facet type-ahead search.
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

    loaders(({ values }) => ({
        // One request for all facets; results are bucketed by facet key (no flicker — the previous
        // map persists until the fresh batch arrives).
        facetValues: [
            {} as Record<string, _LogFacetValueApi[]>,
            {
                loadFacetValues: async (_: null, breakpoint) => {
                    await breakpoint(300)
                    const facets = values.facets
                    if (!values.currentTeamId || facets.length === 0) {
                        return {}
                    }
                    const group = values.queryFilterGroup as UniversalFiltersGroup
                    const filterGroup = ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ??
                        []) as unknown as _LogPropertyFilterApi[]
                    const response = await logsFacetValuesMultiCreate(String(values.currentTeamId), {
                        query: {
                            facets: facets.map((facet) => facetSpec(facet, values.facetSearch[facet.key])),
                            dateRange: values.utcDateRange,
                            severityLevels: values.filters.severityLevels ?? [],
                            serviceNames: values.filters.serviceNames ?? [],
                            searchTerm: values.filters.searchTerm || undefined,
                            filterGroup,
                        },
                    })
                    breakpoint()
                    const byKey: Record<string, _LogFacetValueApi[]> = {}
                    for (const row of response.results) {
                        ;(byKey[row.facetKey] ??= []).push({ value: row.value, count: row.count })
                    }
                    return byKey
                },
            },
        ],
    })),

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
