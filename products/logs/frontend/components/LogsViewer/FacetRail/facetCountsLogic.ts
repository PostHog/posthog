import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import { UniversalFiltersGroup } from '~/types'

import { logsViewerFiltersLogic } from 'products/logs/frontend/components/LogsViewer/Filters/logsViewerFiltersLogic'

import { logsFacetValuesCreate } from '../../../generated/api'
import { _LogFacetValueApi, _LogPropertyFilterApi, _LogsFacetValuesBodyApi } from '../../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'
import { FACETS, FacetConfig } from './facets'

// Broad, filter-independent window for the "which resource attributes does this tenant emit" probe.
// Cheap: keys-only group-by on the log_attributes aggregation table (no value scan).
const PRESENCE_LOOKBACK = { date_from: '-90d' }

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
        // Facets being refreshed by a filter-change reload. Single-flight (its own breakpoint), so the
        // whole set clears together on settle. null arg = all facets.
        loadingReloadKeys: [
            [] as string[],
            {
                loadFacetValues: (_, facetKeys: string[] | null) => facetKeys ?? FACETS.map((f) => f.key),
                loadFacetValuesSuccess: () => [],
                loadFacetValuesFailure: () => [],
            },
        ],
        // The single facet whose type-ahead search is in flight. Single-flight across facets (the per-key
        // loader shares one breakpoint), so a new search supersedes the previous one rather than stacking.
        loadingSearchKey: [
            null as string | null,
            {
                loadFacetValuesForKey: (_, facetKey: string) => facetKey,
                loadFacetValuesForKeySuccess: () => null,
                loadFacetValuesForKeyFailure: () => null,
            },
        ],
        // Latches true once the presence probe settles (success or failure). Until then the value
        // fetch is deferred, so column facets aren't fetched on mount and then re-fetched once
        // presence resolves and the resource-attribute facets become visible.
        presenceLoaded: [
            false,
            {
                loadPresentResourceKeysSuccess: () => true,
                loadPresentResourceKeysFailure: () => true,
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
                        const facets = facetKeys
                            ? values.visibleFacets.filter((f) => facetKeys.includes(f.key))
                            : values.visibleFacets
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
            presentResourceKeys: [
                [] as string[],
                {
                    // Which resource attribute keys the tenant emits — gates which curated facets render.
                    loadPresentResourceKeys: async () => {
                        if (!values.currentTeamId) {
                            return []
                        }
                        // Build the URL by hand rather than via the generated client: its fetch URL
                        // builder serializes query params with String(value), turning the dateRange
                        // object into the literal "[object Object]". The backend then fails to parse it
                        // and silently falls back to a 1h window, so the 90-day presence probe is wrong.
                        // JSON-encode dateRange instead (matches serviceFilterLogic).
                        const url = combineUrl(`api/projects/${values.currentTeamId}/logs/attributes`, {
                            attribute_type: 'resource',
                            dateRange: JSON.stringify(PRESENCE_LOOKBACK),
                            limit: 100,
                        }).url
                        // nosemgrep: prefer-codegen-api
                        const response = await api.get(url)
                        return ((response.results ?? []) as { name: string }[]).map((r) => r.name)
                    },
                },
            ],
        }
    }),

    selectors({
        // Column facets always render; resource-attribute facets only when the tenant emits the key.
        visibleFacets: [
            (s) => [s.presentResourceKeys],
            (presentResourceKeys): FacetConfig[] =>
                FACETS.filter((f) => f.source.type === 'column' || presentResourceKeys.includes(f.source.key)),
        ],
        // Per-facet loading state. A filter-change reload and a per-facet search have independent
        // breakpoints and can overlap, so union both sources — otherwise whichever settles first would
        // clear the other's spinners. Keeping them as separate single-flight reducers means neither can
        // leak a stuck spinner: each clears wholesale on its own settle.
        loadingFacetKeys: [
            (s) => [s.loadingReloadKeys, s.loadingSearchKey],
            (loadingReloadKeys: string[], loadingSearchKey: string | null): string[] =>
                loadingSearchKey && !loadingReloadKeys.includes(loadingSearchKey)
                    ? [...loadingReloadKeys, loadingSearchKey]
                    : loadingReloadKeys,
        ],
    }),

    listeners(({ actions }) => ({
        // A facet's search changed — refetch only that facet, via its own action so it doesn't
        // cancel a still-debouncing full reload (independent breakpoint).
        setFacetSearch: ({ facetKey }) => actions.loadFacetValuesForKey(facetKey),
        // Presence settled — drive the first full fetch now that visibleFacets is known. On failure
        // we still fetch so the column facets (Level/Service) load even if the probe errored.
        loadPresentResourceKeysSuccess: () => actions.loadFacetValues(null),
        loadPresentResourceKeysFailure: () => actions.loadFacetValues(null),
    })),

    events(({ actions }) => ({
        afterMount: () => actions.loadPresentResourceKeys(),
    })),

    subscriptions(({ actions, values }) => {
        // Fires on mount (initial load) and on any change. We watch both `filters` (severity, service,
        // search, date, user filterGroup) and `queryFilterGroup` (which folds in pinnedFilters, e.g. the
        // person-tab distinct_id pin) so values re-fetch when the pinned scope changes too. `filterGroup`
        // feeds both, so a normal edit fires both — the 300ms debounce in the loader collapses that.
        const reloadAll = (): void => {
            // Before the presence probe settles, defer to loadPresentResourceKeys{Success,Failure}
            // so we issue one full fetch over the final visible set instead of two.
            if (values.presenceLoaded) {
                actions.loadFacetValues(null)
            }
        }
        return {
            filters: reloadAll,
            queryFilterGroup: reloadAll,
        }
    }),
])
