import { MakeLogicType, actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'

import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { HogQLFilters } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator, TeamType } from '~/types'

import type { TeamPublicType } from '../../../frontend/src/types'
import { McpFacets, mcpFacetsLogic } from './mcpFacetsLogic'

export type MCPSharedQueryFilters = Required<Pick<HogQLFilters, 'filterTestAccounts' | 'properties'>>

export interface MCPSharedFilterParams {
    properties?: string
    filter_test_accounts?: boolean
}

// Marks the "Missing capability" session list, so the GET endpoints can leave it out of the URL.
const FEEDBACK_SESSIONS_LABEL = 'Missing capability'

/** The shared filters as GET params. "Missing capability" is left out: its session list can outgrow a URL. */
export function sharedFilterParams(filters: MCPSharedQueryFilters): MCPSharedFilterParams {
    const properties = filters.properties.filter((filter) => filter.label !== FEEDBACK_SESSIONS_LABEL)
    return {
        properties: properties.length > 0 ? JSON.stringify(properties) : undefined,
        filter_test_accounts: filters.filterTestAccounts || undefined,
    }
}

export function hasFeedbackSessionsFilter(filters: MCPSharedQueryFilters): boolean {
    return filters.properties.some((filter) => filter.label === FEEDBACK_SESSIONS_LABEL)
}

export interface McpFacetFilters {
    tools: string[]
    categories: string[]
    /** $mcp_error_type values. Picking any narrows to errored calls of those types. */
    errors: string[]
    harnesses: string[]
    models: string[]
    slow: boolean
    isNew: boolean
    gaveFeedback: boolean
}

export const DEFAULT_FACET_FILTERS: McpFacetFilters = {
    tools: [],
    categories: [],
    errors: [],
    harnesses: [],
    models: [],
    slow: false,
    isNew: false,
    gaveFeedback: false,
}

const FACET_LIST_KEYS = ['tools', 'categories', 'errors', 'harnesses', 'models'] as const

// Matches no tool, for "New tools" when no tool is new: an empty list would match every call instead.
const NO_NEW_TOOLS = '$mcp_no_new_tools'
// Matches no session, for "Missing capability" when no agent reported one.
const NO_FEEDBACK_SESSIONS = '$mcp_no_feedback_sessions'

const FACET_FLAG_PARAMS = { slow: 'slow', isNew: 'is_new', gaveFeedback: 'feedback' } as const

/** Tools whose first call in the lookback falls on or after the range's start. */
export function newToolNames(toolFirstSeen: Record<string, string>, dateFrom: string | null | undefined): string[] {
    const start = dateStringToDayJs(dateFrom ?? '-7d') ?? dayjs().subtract(7, 'day')
    return Object.entries(toolFirstSeen)
        .filter(([, firstSeen]) => !dayjs(firstSeen).isBefore(start))
        .map(([tool]) => tool)
        .sort()
}

// The MCP endpoints take event property filters only, so the facets become filters on the raw properties.
// ponytail: an exec-wrapped call or a client known only by user agent misses; send expressions if that matters.
export function facetPropertyFilters(
    facets: McpFacetFilters,
    slowThresholdMs: number | null,
    newTools: string[] | null = null,
    feedbackSessions: string[] | null = null
): AnyPropertyFilter[] {
    const filters: AnyPropertyFilter[] = (
        [
            ['$mcp_tool_name', facets.tools],
            ['$mcp_tool_category', facets.categories],
            ['$mcp_error_type', facets.errors],
            ['$virt_mcp_harness', facets.harnesses],
            ['$mcp_llm_model', facets.models],
        ] as const
    )
        .filter(([, values]) => values.length > 0)
        .map(([key, values]) => ({
            type: PropertyFilterType.Event,
            key,
            value: [...values],
            operator: PropertyOperator.Exact,
        }))
    if (newTools !== null) {
        filters.push({
            type: PropertyFilterType.Event,
            key: '$mcp_tool_name',
            value: newTools.length > 0 ? newTools : [NO_NEW_TOOLS],
            operator: PropertyOperator.Exact,
        })
    }
    if (feedbackSessions !== null) {
        filters.push({
            type: PropertyFilterType.Event,
            key: '$session_id',
            value: feedbackSessions.length > 0 ? feedbackSessions : [NO_FEEDBACK_SESSIONS],
            operator: PropertyOperator.Exact,
            label: FEEDBACK_SESSIONS_LABEL,
        })
    }
    if (slowThresholdMs !== null) {
        filters.push({
            type: PropertyFilterType.Event,
            key: '$mcp_duration_ms',
            value: slowThresholdMs,
            operator: PropertyOperator.GreaterThan,
        })
    }
    return filters
}

const SHARED_URL_PARAMS = [
    'date_from',
    'date_to',
    'properties',
    'filter_test_accounts',
    ...FACET_LIST_KEYS,
    ...Object.values(FACET_FLAG_PARAMS),
] as const

export function pickSharedFilterParams(searchParams: Record<string, any>): Record<string, any> {
    return Object.fromEntries(
        SHARED_URL_PARAMS.filter((key) => key in searchParams).map((key) => [key, searchParams[key]])
    )
}

/** Activity URL with the shared filters plus one facet or property. */
export function activityUrlWithFilter(
    searchParams: Record<string, any>,
    change: { facets?: Partial<McpFacetFilters>; property?: AnyPropertyFilter }
): string {
    const params = pickSharedFilterParams(searchParams)
    for (const [key, value] of Object.entries(change.facets ?? {})) {
        params[FACET_FLAG_PARAMS[key as keyof typeof FACET_FLAG_PARAMS] ?? key] = value
    }
    if (change.property) {
        params.properties = [...(Array.isArray(params.properties) ? params.properties : []), change.property]
    }
    return combineUrl(urls.mcpAnalyticsActivity(), params).url
}

export const MCP_ANALYTICS_FILTER_ROUTES = [
    urls.mcpAnalyticsActivity(),
    urls.mcpAnalyticsDashboard(),
    urls.mcpAnalyticsSessions(),
    urls.mcpAnalyticsToolQuality(),
    `${urls.mcpAnalyticsToolQuality()}/:toolName`,
    urls.mcpAnalyticsIntentClustering(),
    urls.mcpAnalyticsMissingCapabilities(),
    urls.mcpAnalyticsNotifications(),
]

interface UrlFilters {
    filterTestAccountsOverride: boolean | null
    propertyFilters: AnyPropertyFilter[]
    facetFilters: McpFacetFilters
}

export function writeSharedFilterParams(
    searchParams: Record<string, any>,
    { filterTestAccountsOverride, propertyFilters, facetFilters }: UrlFilters
): void {
    for (const key of FACET_LIST_KEYS) {
        if (facetFilters[key].length > 0) {
            searchParams[key] = facetFilters[key]
        } else {
            delete searchParams[key]
        }
    }
    // Drop the retired `result` param.
    delete searchParams.result
    for (const [key, param] of Object.entries(FACET_FLAG_PARAMS)) {
        if (facetFilters[key as keyof typeof FACET_FLAG_PARAMS]) {
            searchParams[param] = true
        } else {
            delete searchParams[param]
        }
    }
    if (filterTestAccountsOverride === null) {
        delete searchParams.filter_test_accounts
    } else {
        searchParams.filter_test_accounts = filterTestAccountsOverride
    }
    if (propertyFilters.length > 0) {
        searchParams.properties = propertyFilters
    } else {
        delete searchParams.properties
    }
}

// kea-router may hand a boolean param back already coerced, or as its string form.
export function parseUrlBoolean(raw: unknown): boolean | null {
    return raw === true || raw === 'true' ? true : raw === false || raw === 'false' ? false : null
}

// A single value can arrive as a bare string rather than a one-element array.
function parseUrlList(raw: unknown): string[] {
    return Array.isArray(raw) ? raw.map(String) : typeof raw === 'string' && raw ? [raw] : []
}

function parseUrlFilters(searchParams: Record<string, any>): UrlFilters {
    return {
        filterTestAccountsOverride: parseUrlBoolean(searchParams.filter_test_accounts),
        propertyFilters: Array.isArray(searchParams.properties) ? searchParams.properties : [],
        facetFilters: {
            tools: parseUrlList(searchParams.tools),
            categories: parseUrlList(searchParams.categories),
            errors: parseUrlList(searchParams.errors),
            harnesses: parseUrlList(searchParams.harnesses),
            models: parseUrlList(searchParams.models),
            slow: parseUrlBoolean(searchParams.slow) === true,
            isNew: parseUrlBoolean(searchParams.is_new) === true,
            gaveFeedback: parseUrlBoolean(searchParams.feedback) === true,
        },
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsFiltersLogicValues {
    currentTeam: TeamPublicType | TeamType | null // teamLogic
    filterTestAccounts: boolean
    filterTestAccountsOverride: boolean | null
    propertyFilters: AnyPropertyFilter[]
    queryFilters: MCPSharedQueryFilters
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsFiltersLogicActions {
    hydrateFilters: (
        filterTestAccountsOverride: boolean | null,
        propertyFilters: AnyPropertyFilter[]
    ) => {
        filterTestAccountsOverride: boolean | null
        propertyFilters: AnyPropertyFilter[]
    }
    setFilterTestAccounts: (filterTestAccounts: boolean | null) => {
        filterTestAccounts: boolean | null
    }
    setPropertyFilters: (properties: AnyPropertyFilter[]) => {
        properties: AnyPropertyFilter[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface mcpAnalyticsFiltersLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        filterTestAccounts: (
            filterTestAccountsOverride: boolean | null,
            currentTeam: TeamPublicType | TeamType | null
        ) => boolean
        queryFilters: (filterTestAccounts: boolean, propertyFilters: AnyPropertyFilter[]) => MCPSharedQueryFilters
    }
}

export type mcpAnalyticsFiltersLogicType = MakeLogicType<
    mcpAnalyticsFiltersLogicValues,
    mcpAnalyticsFiltersLogicActions,
    Record<string, any>,
    mcpAnalyticsFiltersLogicMeta
>

export const mcpAnalyticsFiltersLogic = kea<mcpAnalyticsFiltersLogicType>([
    path(['products', 'mcp_analytics', 'frontend', 'mcpAnalyticsFiltersLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], mcpFacetsLogic, ['facets'], router, ['searchParams']],
    })),
    actions({
        hydrateFilters: (
            filterTestAccountsOverride: boolean | null,
            propertyFilters: AnyPropertyFilter[],
            facetFilters: McpFacetFilters
        ) => ({
            filterTestAccountsOverride,
            propertyFilters,
            facetFilters,
        }),
        setFilterTestAccounts: (filterTestAccounts: boolean | null) => ({ filterTestAccounts }),
        setPropertyFilters: (properties: AnyPropertyFilter[]) => ({ properties }),
        setFacetFilters: (facetFilters: Partial<McpFacetFilters>) => ({ facetFilters }),
    }),
    reducers({
        filterTestAccountsOverride: [
            null as boolean | null,
            {
                hydrateFilters: (_, { filterTestAccountsOverride }): boolean | null => filterTestAccountsOverride,
                setFilterTestAccounts: (_, { filterTestAccounts }): boolean | null => filterTestAccounts,
            },
        ],
        propertyFilters: [
            [] as AnyPropertyFilter[],
            {
                hydrateFilters: (_, { propertyFilters }): AnyPropertyFilter[] => propertyFilters,
                setPropertyFilters: (_, { properties }): AnyPropertyFilter[] => properties,
            },
        ],
        facetFilters: [
            DEFAULT_FACET_FILTERS,
            {
                hydrateFilters: (_, { facetFilters }): McpFacetFilters => facetFilters,
                setFacetFilters: (state, { facetFilters }): McpFacetFilters => ({ ...state, ...facetFilters }),
            },
        ],
    }),
    selectors({
        filterTestAccounts: [
            (s) => [s.filterTestAccountsOverride, s.currentTeam],
            (override: boolean | null, currentTeam: TeamType | null): boolean =>
                override ?? !!currentTeam?.test_account_filters_default_checked,
        ],
        // Its own selector so the facets loading leaves queryFilters untouched while "Slow" is off.
        slowThresholdMs: [
            (s) => [s.facetFilters, s.facets],
            (facetFilters: McpFacetFilters, facets: McpFacets | null): number | null =>
                facetFilters.slow && facets?.p95 ? Math.round(facets.p95) : null,
        ],
        // A string, so other URL changes and the facets loading leave queryFilters untouched while it is off.
        newToolsKey: [
            (s) => [s.facetFilters, s.facets, s.searchParams],
            (
                facetFilters: McpFacetFilters,
                facets: McpFacets | null,
                searchParams: Record<string, any>
            ): string | null =>
                facetFilters.isNew
                    ? JSON.stringify(newToolNames(facets?.toolFirstSeen ?? {}, searchParams.date_from))
                    : null,
        ],
        // A string for the same reason as newToolsKey.
        feedbackSessionsKey: [
            (s) => [s.facetFilters, s.facets],
            (facetFilters: McpFacetFilters, facets: McpFacets | null): string | null =>
                facetFilters.gaveFeedback ? JSON.stringify(facets?.feedbackSessions ?? []) : null,
        ],
        queryFilters: [
            (s) => [
                s.filterTestAccounts,
                s.propertyFilters,
                s.facetFilters,
                s.slowThresholdMs,
                s.newToolsKey,
                s.feedbackSessionsKey,
            ],
            (
                filterTestAccounts: boolean,
                propertyFilters: AnyPropertyFilter[],
                facetFilters: McpFacetFilters,
                slowThresholdMs: number | null,
                newToolsKey: string | null,
                feedbackSessionsKey: string | null
            ): MCPSharedQueryFilters => ({
                filterTestAccounts,
                properties: [
                    ...propertyFilters.filter(isValidPropertyFilter),
                    ...facetPropertyFilters(
                        facetFilters,
                        slowThresholdMs,
                        newToolsKey === null ? null : (JSON.parse(newToolsKey) as string[]),
                        feedbackSessionsKey === null ? null : (JSON.parse(feedbackSessionsKey) as string[])
                    ),
                ],
            }),
        ],
        hasActiveFacetFilters: [
            (s) => [s.facetFilters],
            (facetFilters: McpFacetFilters): boolean =>
                JSON.stringify(facetFilters) !== JSON.stringify(DEFAULT_FACET_FILTERS),
        ],
    }),
    actionToUrl(({ values }) => {
        const syncUrl = (): [string, Record<string, any>, Record<string, any>, { replace: boolean }] => {
            const { currentLocation } = router.values
            const searchParams = { ...currentLocation.searchParams }
            writeSharedFilterParams(searchParams, values)
            return [currentLocation.pathname, searchParams, currentLocation.hashParams, { replace: true }]
        }
        return {
            setFilterTestAccounts: syncUrl,
            setPropertyFilters: syncUrl,
            setFacetFilters: syncUrl,
        }
    }),
    urlToAction(({ actions, values }) => {
        const hydrate = (_: Record<string, any>, searchParams: Record<string, any>): void => {
            const { filterTestAccountsOverride, propertyFilters, facetFilters } = parseUrlFilters(searchParams)
            if (
                filterTestAccountsOverride !== values.filterTestAccountsOverride ||
                JSON.stringify(propertyFilters) !== JSON.stringify(values.propertyFilters) ||
                JSON.stringify(facetFilters) !== JSON.stringify(values.facetFilters)
            ) {
                actions.hydrateFilters(filterTestAccountsOverride, propertyFilters, facetFilters)
            }
        }
        return Object.fromEntries(MCP_ANALYTICS_FILTER_ROUTES.map((route) => [route, hydrate]))
    }),
])
