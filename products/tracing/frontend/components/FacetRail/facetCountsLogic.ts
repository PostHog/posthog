import { connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
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
 * this fetches one attribute-breakdown request per facet in FACETS, keyed by facet.key.
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

    reducers({
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
        const fetchFacet = async (facet: FacetConfig): Promise<_TracingAttributeBreakdownRowApi[]> => {
            if (!values.currentTeamId) {
                return []
            }
            // The endpoint takes the flat inner filter list.
            const filterGroup = innerFilters(values.queryFilterGroup) as unknown as _SpanPropertyFilterApi[]
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
                    filterGroup,
                },
            })
            return response.results
        }

        // Fetch each facet independently and merge into the existing record. allSettled (not all) so
        // one facet's failed request leaves the others' counts intact instead of wiping the batch.
        const mergeFetched = async (
            facets: FacetConfig[]
        ): Promise<Record<string, _TracingAttributeBreakdownRowApi[]>> => {
            const settled = await Promise.allSettled(
                facets.map(async (facet) => [facet.key, await fetchFacet(facet)] as const)
            )
            const fetched = settled
                .filter(
                    (s): s is PromiseFulfilledResult<readonly [string, _TracingAttributeBreakdownRowApi[]]> =>
                        s.status === 'fulfilled'
                )
                .map((s) => s.value)
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
