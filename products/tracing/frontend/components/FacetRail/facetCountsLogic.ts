import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { teamLogic } from 'scenes/teamLogic'

import { DateRange } from '~/queries/schema/schema-general'
import { UniversalFiltersGroup } from '~/types'

import {
    TRACING_SCENE_VIEWER_ID,
    tracingFiltersLogic,
    TracingFiltersLogicProps,
} from 'products/tracing/frontend/tracingFiltersLogic'

import { tracingSpansAttributeBreakdownCreate, tracingSpansAttributesRetrieve } from '../../generated/api'
import {
    _SpanPropertyFilterApi,
    _SpanPropertyFilterOperatorEnumApi,
    _TracingAttributeBreakdownRowApi,
    SpanPropertyTypeEnumApi,
    TracingSpansAttributesRetrieveAttributeType,
} from '../../generated/api.schemas'
import type { facetCountsLogicType } from './facetCountsLogicType'
import { FACETS, FacetConfig, innerFilters } from './facets'

export interface FacetCountsLogicProps {
    id: string
}

/** The query-relevant slice of filter state — the breakdown requests read exactly these three. */
export interface BreakdownScope {
    utcDateRange: DateRange
    serviceNames: string[]
    queryFilterGroup: UniversalFiltersGroup
}

/**
 * Per-facet values + counts, cross-filtered server-side: each facet's results reflect every active
 * filter except its own selection (excludeBreakdownFilter drops the facet's own column, serviceNames,
 * or attribute filter). Values come back ordered by count descending. The rail is config-driven, so
 * this fetches one attribute-breakdown request per facet in FACETS, keyed by facet.key. A per-facet
 * type-ahead search re-fetches only that facet (its CH group-by is a full scan, so we don't refetch
 * the others on every keystroke).
 */
export const facetCountsLogic = kea<facetCountsLogicType>([
    props({ id: TRACING_SCENE_VIEWER_ID } as FacetCountsLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'tracing', 'frontend', 'components', 'FacetRail', 'facetCountsLogic', key]),

    connect((props: FacetCountsLogicProps) => ({
        values: [
            tracingFiltersLogic({ id: props.id } as TracingFiltersLogicProps),
            ['serviceNames', 'utcDateRange', 'queryFilterGroup'],
            teamLogic,
            ['currentTeamId'],
        ],
    })),

    actions({
        setFacetSearch: (facetKey: string, search: string) => ({ facetKey, search }),
        // Dispatched by the loaders after each allSettled batch: `attempted` facets leave the error
        // set (they got a fresh verdict), `failed` ones (re-)enter it.
        setFacetFetchErrors: (attempted: string[], failed: string[]) => ({ attempted, failed }),
    }),

    reducers({
        facetSearch: [
            {} as Record<string, string>,
            {
                setFacetSearch: (state, { facetKey, search }) => ({ ...state, [facetKey]: search }),
            },
        ],
        // Facets whose latest fetch failed — drives the per-facet inline error state, so one broken
        // breakdown shows in place instead of blanking the rail.
        erroredFacetKeys: [
            [] as string[],
            {
                setFacetFetchErrors: (state, { attempted, failed }) => [
                    ...state.filter((key) => !attempted.includes(key)),
                    ...failed,
                ],
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

    loaders(({ actions, values }) => {
        const fetchFacet = async (facet: FacetConfig): Promise<_TracingAttributeBreakdownRowApi[]> => {
            if (!values.currentTeamId) {
                return []
            }
            // The endpoint takes the flat inner filter list. The stored filters carry the app-side
            // enums (PropertyFilterType/PropertyOperator) which are nominally distinct from the
            // generated string-union enums despite identical runtime values, so mapping onto the
            // generated shape type-checks the field structure (key/value) while casting only the two
            // enum fields.
            const filterGroup: _SpanPropertyFilterApi[] = innerFilters(values.queryFilterGroup).map((f) => ({
                key: f.key,
                type: f.type as unknown as SpanPropertyTypeEnumApi,
                operator: f.operator as unknown as _SpanPropertyFilterOperatorEnumApi,
                value: f.value,
            }))
            const target =
                facet.source.type === 'column'
                    ? { breakdownKey: facet.source.column, breakdownType: SpanPropertyTypeEnumApi.Span }
                    : { breakdownKey: facet.source.key, breakdownType: SpanPropertyTypeEnumApi.SpanResourceAttribute }
            const response = await tracingSpansAttributeBreakdownCreate(String(values.currentTeamId), {
                query: {
                    ...target,
                    excludeBreakdownFilter: true,
                    dateRange: values.utcDateRange,
                    serviceNames: values.serviceNames ?? [],
                    facetSearch: values.facetSearch[facet.key] || undefined,
                    filterGroup,
                },
            })
            return response.results
        }

        // Fetch each facet independently and merge into the existing record. allSettled (not all) so
        // one facet's failed request leaves the others' counts intact instead of wiping the batch.
        // Failures are recorded per facet for the inline error state.
        const mergeFetched = async (
            facets: FacetConfig[]
        ): Promise<Record<string, _TracingAttributeBreakdownRowApi[]>> => {
            // The search term each request is about to carry. A full reload and a per-facet search
            // have independent breakpoints, so a reload issued before the user typed can settle
            // after the narrowed search response — merging it would put unsearched rows under a
            // still-filled search box. Dropping stale-term rows leaves the fresher response's in place.
            const searchAtRequest = Object.fromEntries(facets.map((f) => [f.key, values.facetSearch[f.key] ?? '']))
            const settled = await Promise.allSettled(
                facets.map(async (facet) => [facet.key, await fetchFacet(facet)] as const)
            )
            const fulfilled = settled
                .filter(
                    (s): s is PromiseFulfilledResult<readonly [string, _TracingAttributeBreakdownRowApi[]]> =>
                        s.status === 'fulfilled'
                )
                .map((s) => s.value)
            // Error state keys off fulfillment: a stale-term fetch still succeeded, it just doesn't merge.
            const fulfilledKeys = new Set(fulfilled.map(([key]) => key))
            const attemptedKeys = facets.map((f) => f.key)
            // Fires before the final breakpoint, so a superseded batch can record error state — the
            // winning batch immediately overwrites it, since every batch reports all attempted keys.
            actions.setFacetFetchErrors(
                attemptedKeys,
                attemptedKeys.filter((key) => !fulfilledKeys.has(key))
            )
            const fetched = fulfilled.filter(([key]) => (values.facetSearch[key] ?? '') === searchAtRequest[key])
            return { ...values.facetValues, ...Object.fromEntries(fetched) }
        }

        return {
            facetValues: [
                {} as Record<string, _TracingAttributeBreakdownRowApi[]>,
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
                    // Reads the trace_attributes rollup keys-only; no date range parameter (server default window).
                    loadPresentResourceKeys: async () => {
                        if (!values.currentTeamId) {
                            return []
                        }
                        const response = await tracingSpansAttributesRetrieve(String(values.currentTeamId), {
                            attribute_type: TracingSpansAttributesRetrieveAttributeType.SpanResourceAttribute,
                            limit: 100,
                        })
                        return response.results.map((r) => r.name)
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
        // The subset of filter state the breakdown queries actually depend on, built from the stable
        // leaf values — not the `filters` roll-up, which also carries presentation state (viewMode,
        // orderBy, compareMode, overlay windows) and gets a new identity whenever any of it changes.
        // Subscribing to this keeps a view-mode or sort toggle from refetching every facet.
        breakdownScope: [
            (s) => [s.utcDateRange, s.serviceNames, s.queryFilterGroup],
            (utcDateRange, serviceNames, queryFilterGroup): BreakdownScope => ({
                utcDateRange,
                serviceNames,
                queryFilterGroup,
            }),
        ],
    }),

    listeners(({ actions }) => ({
        // A facet's search changed — refetch only that facet, via its own action so it doesn't
        // cancel a still-debouncing full reload (independent breakpoint).
        setFacetSearch: ({ facetKey }) => actions.loadFacetValuesForKey(facetKey),
        // Presence settled — drive the first full fetch now that visibleFacets is known. On failure
        // we still fetch so the column facets (Service/Status) load even if the probe errored.
        loadPresentResourceKeysSuccess: () => actions.loadFacetValues(null),
        loadPresentResourceKeysFailure: () => actions.loadFacetValues(null),
    })),

    events(({ actions }) => ({
        afterMount: () => actions.loadPresentResourceKeys(),
    })),

    subscriptions(({ actions, values }) => ({
        // Fires on any change to the query-relevant filter state (date range, services, filter group
        // including an embedder's pinned scope). Before the presence probe settles, defer to
        // loadPresentResourceKeys{Success,Failure} so we issue one full fetch over the final visible
        // set instead of two.
        breakdownScope: () => {
            if (values.presenceLoaded) {
                actions.loadFacetValues(null)
            }
        },
    })),
])
