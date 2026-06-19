import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi, _LogsFacetValuesBodyApi } from '../../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'
import { FACETS, FacetConfig } from './facets'

export interface FacetCountsLogicProps {
    id: string
}

/**
 * Per-facet values + counts, cross-filtered server-side: each facet's results reflect every active
 * filter except its own selection (the backend excludes the facet's own column or resource-attribute
 * filter). Values come back ordered by count descending. The rail is config-driven, so this fetches
 * one request per facet in FACETS, keyed by facet.key. A per-facet type-ahead search re-fetches only
 * that facet (its CH group-by is a full scan, so we don't refetch the others on every keystroke).
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
        setFacetSearch: (facetKey: string, search: string) => ({ facetKey, search }),
    }),

    reducers({
        facetSearch: [
            {} as Record<string, string>,
            {
                setFacetSearch: (state, { facetKey, search }) => ({ ...state, [facetKey]: search }),
            },
        ],
        // Keys currently being fetched, so each facet can show its own loading state. Set from the
        // load action's argument (null = all facets); cleared when the fetch settles.
        loadingFacetKeys: [
            [] as string[],
            {
                loadFacetValues: (_, facetKeys: string[] | null) => facetKeys ?? FACETS.map((f) => f.key),
                loadFacetValuesSuccess: () => [],
                loadFacetValuesFailure: () => [],
                loadFacetValuesForKey: (_, facetKey: string) => [facetKey],
                loadFacetValuesForKeySuccess: () => [],
                loadFacetValuesForKeyFailure: () => [],
            },
        ],
    }),

    loaders(({ values }) => {
        const fetchFacet = async (facet: FacetConfig): Promise<_LogFacetValueApi[]> => {
            if (!values.currentTeamId) {
                return []
            }
            const group = values.queryFilterGroup as UniversalFiltersGroup
            const filterGroup = ((group?.values?.[0] as UniversalFiltersGroup | undefined)?.values ??
                []) as unknown as _LogPropertyFilterApi[]
            const target: Partial<_LogsFacetValuesBodyApi> =
                facet.source.type === 'column'
                    ? { facetField: facet.source.column }
                    : { facetResourceAttribute: facet.source.key }
            const response = await logsFacetValuesCreate(String(values.currentTeamId), {
                query: {
                    ...target,
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

        // Fetch each facet independently and merge into the existing record. allSettled (not all) so
        // one facet's failed request leaves the others' counts intact instead of wiping the batch.
        const mergeFetched = async (facets: FacetConfig[]): Promise<Record<string, _LogFacetValueApi[]>> => {
            const settled = await Promise.allSettled(
                facets.map(async (facet) => [facet.key, await fetchFacet(facet)] as const)
            )
            const fetched = settled
                .filter(
                    (s): s is PromiseFulfilledResult<readonly [string, _LogFacetValueApi[]]> => s.status === 'fulfilled'
                )
                .map((s) => s.value)
            return { ...values.facetValues, ...Object.fromEntries(fetched) }
        }

        return {
            facetValues: [
                {} as Record<string, _LogFacetValueApi[]>,
                {
                    // Refetch all facets (null) or a subset — used when filters change.
                    loadFacetValues: async (facetKeys: string[] | null, breakpoint) => {
                        await breakpoint(300)
                        const facets = facetKeys ? FACETS.filter((f) => facetKeys.includes(f.key)) : FACETS
                        const result = await mergeFetched(facets)
                        breakpoint()
                        return result
                    },
                    // A single facet's type-ahead search. Separate action so its breakpoint is independent:
                    // typing in one facet's search must not cancel a still-debouncing full reload.
                    loadFacetValuesForKey: async (facetKey: string, breakpoint) => {
                        await breakpoint(300)
                        const facet = FACETS.find((f) => f.key === facetKey)
                        const result = facet ? await mergeFetched([facet]) : values.facetValues
                        breakpoint()
                        return result
                    },
                },
            ],
        }
    }),

    listeners(({ actions }) => ({
        // A facet's search changed — refetch only that facet, via its own action so it doesn't
        // cancel a still-debouncing full reload (independent breakpoint).
        setFacetSearch: ({ facetKey }) => actions.loadFacetValuesForKey(facetKey),
    })),

    subscriptions(({ actions }) => {
        // Fires on mount (initial load) and on any change. We watch both `filters` (severity, service,
        // search, date, user filterGroup) and `queryFilterGroup` (which folds in pinnedFilters, e.g. the
        // person-tab distinct_id pin) so values re-fetch when the pinned scope changes too. `filterGroup`
        // feeds both, so a normal edit fires both — the 300ms debounce in the loader collapses that.
        const reloadAll = (): void => actions.loadFacetValues(null)
        return {
            filters: reloadAll,
            queryFilterGroup: reloadAll,
        }
    }),
])
