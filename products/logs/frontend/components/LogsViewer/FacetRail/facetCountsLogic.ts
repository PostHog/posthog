import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi } from '../../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'
import { FacetField } from './facets'

export interface FacetCountsLogicProps {
    id: string
}

/**
 * Per-facet values + counts, cross-filtered server-side: each facet's results reflect every active
 * filter except its own selection (see the backend's exclude_facet_field). Values come back ordered
 * by count descending. Dynamic facets (e.g. service) also pass a per-facet type-ahead search so they
 * can match values beyond the returned window.
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

    actions({
        setFacetSearch: (facetField: FacetField, search: string) => ({ facetField, search }),
    }),

    reducers({
        facetSearch: [
            {} as Record<string, string>,
            {
                setFacetSearch: (state, { facetField, search }) => ({ ...state, [facetField]: search }),
            },
        ],
    }),

    loaders(({ values }) => {
        const fetchValues = async (facetField: FacetField): Promise<_LogFacetValueApi[]> => {
            if (!values.currentTeamId) {
                return []
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
                    facetSearch: values.facetSearch[facetField] || undefined,
                    filterGroup,
                },
            })
            return response.results
        }

        return {
            levelValues: [
                [] as _LogFacetValueApi[],
                {
                    loadLevelValues: async (_: null, breakpoint) => {
                        await breakpoint(300)
                        const results = await fetchValues('severity_text')
                        breakpoint()
                        return results
                    },
                },
            ],
            serviceValues: [
                [] as _LogFacetValueApi[],
                {
                    loadServiceValues: async (_: null, breakpoint) => {
                        await breakpoint(300)
                        const results = await fetchValues('service_name')
                        breakpoint()
                        return results
                    },
                },
            ],
        }
    }),

    listeners(({ actions }) => {
        // Re-fetch the facet whose search term changed. Typed by FacetField so adding a field is a
        // compile error until its loader is wired here (fixed facets just never receive a search).
        const reloaders: Record<FacetField, () => void> = {
            severity_text: () => actions.loadLevelValues(null),
            service_name: () => actions.loadServiceValues(null),
        }
        return {
            setFacetSearch: ({ facetField }) => reloaders[facetField](),
        }
    }),

    subscriptions(({ actions }) => {
        // Fires on mount (initial load) and on any change. We watch both `filters` (severity,
        // service, search, date, user filterGroup) and `queryFilterGroup` (which folds in
        // pinnedFilters, e.g. the person-tab distinct_id pin) so values re-fetch when the pinned
        // scope changes too. `filterGroup` feeds both, so a normal edit fires both — the 300ms
        // debounce in each loader collapses that into one request.
        const reload = (): void => {
            actions.loadLevelValues(null)
            actions.loadServiceValues(null)
        }
        return {
            filters: reload,
            queryFilterGroup: reload,
        }
    }),
])
