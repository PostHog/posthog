import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { sqlEditorLogic } from 'scenes/data-warehouse/editor/sqlEditorLogic'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    DataTableNode,
    EndpointRefreshMode,
    EndpointRunRequest,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isHogQLQuery, isInsightQueryNode } from '~/queries/utils'
import { Breadcrumb, EndpointType, EndpointVersionType } from '~/types'

import { endpointLogic } from './endpointLogic'
import type { endpointSceneLogicType } from './endpointSceneLogicType'

// Default data freshness when none is set on the endpoint version (must match backend DEFAULT_DATA_FRESHNESS_SECONDS)
const DEFAULT_DATA_FRESHNESS_SECONDS = 86400

// Query types that support user-configurable breakdown filtering
const BREAKDOWN_SUPPORTED_QUERY_TYPES = new Set([NodeKind.TrendsQuery, NodeKind.RetentionQuery])

export function extractBreakdownPropertyNames(query: unknown): string[] {
    // Single source of truth for reading breakdown property names out of a query on the
    // frontend — mirrors the backend's canonical extractor, including the legacy list form.
    if (!query || typeof query !== 'object') {
        return []
    }
    const breakdownFilter = (
        query as { breakdownFilter?: { breakdown?: unknown; breakdowns?: { property?: unknown }[] } | null }
    ).breakdownFilter
    if (!breakdownFilter) {
        return []
    }
    const legacy = breakdownFilter.breakdown
    if (Array.isArray(legacy)) {
        return legacy.filter((b): b is string => typeof b === 'string' && !!b)
    }
    if (typeof legacy === 'string' && legacy) {
        return [legacy]
    }
    return (breakdownFilter.breakdowns ?? [])
        .map((b) => (typeof b?.property === 'string' ? b.property : null))
        .filter((p): p is string => !!p)
}

/**
 * Playground variable contract — drives the typed form, the Send checkbox state, and the
 * code-example snippets. Stays in lockstep with the runtime contract enforced by
 * `_get_required_variables` / `_get_allowed_variables` on the backend.
 */
export type PlaygroundVariableKind = 'hogql' | 'breakdown' | 'date'
export type PlaygroundVariableInputType = 'text' | 'number' | 'boolean' | 'date' | 'list'

export interface PlaygroundVariableSpec {
    /** code_name (HogQL) or property name (insight breakdown / date_from / date_to). */
    name: string
    kind: PlaygroundVariableKind
    inputType: PlaygroundVariableInputType
    /** Server will 400 if this variable is omitted at /run time. */
    required: boolean
    /** Seed value for the input. */
    defaultValue: unknown
    /** Initial state of the Send checkbox. */
    defaultSent: boolean
    /** When true, the Send checkbox is disabled — used for required vars that can't be sensibly unsent. */
    sendLocked: boolean
}

/**
 * Derive the playground form's per-variable contract from an endpoint version. The form
 * uses this to render the right widget per variable and to set Send-checkbox state /
 * lock state in a way that matches what the server will accept at /run time.
 */
export function derivePlaygroundVariableSpecs(
    endpoint: EndpointVersionType | null,
    viewingVersion: EndpointVersionType | null
): PlaygroundVariableSpec[] {
    if (!endpoint) {
        return []
    }

    const effective = viewingVersion ?? endpoint
    const query = effective.query
    const isMaterialized = effective.is_materialized
    const optionalBreakdowns = new Set(effective.optional_breakdown_properties ?? [])
    const specs: PlaygroundVariableSpec[] = []

    if (query?.kind === NodeKind.HogQLQuery) {
        const variables = (query as any).variables ?? {}
        Object.values(variables).forEach((value: any) => {
            const codeName = value?.code_name
            if (!codeName) {
                return
            }
            const defaultValue = value?.value ?? ''
            const hasDefault = defaultValue !== '' && defaultValue !== null && defaultValue !== undefined
            specs.push({
                name: codeName,
                kind: 'hogql',
                inputType: 'text',
                // Materialized HogQL endpoints require every materialized variable; inline HogQL
                // substitutes the default or NULL, so it's effectively optional.
                required: isMaterialized,
                defaultValue,
                defaultSent: isMaterialized || !hasDefault,
                sendLocked: isMaterialized,
            })
        })
        return specs
    }

    if (isInsightQueryNode(query)) {
        if (query?.kind && BREAKDOWN_SUPPORTED_QUERY_TYPES.has(query.kind as NodeKind)) {
            extractBreakdownPropertyNames(query).forEach((name) => {
                const isOptional = optionalBreakdowns.has(name)
                specs.push({
                    name,
                    kind: 'breakdown',
                    inputType: 'text',
                    required: !isOptional,
                    defaultValue: '',
                    defaultSent: !isOptional,
                    sendLocked: !isOptional,
                })
            })
        }
        if (!isMaterialized) {
            specs.push(
                {
                    name: 'date_from',
                    kind: 'date',
                    inputType: 'text',
                    required: false,
                    defaultValue: '-7d',
                    defaultSent: false,
                    sendLocked: false,
                },
                {
                    name: 'date_to',
                    kind: 'date',
                    inputType: 'text',
                    required: false,
                    defaultValue: '',
                    defaultSent: false,
                    sendLocked: false,
                }
            )
        }
    }

    return specs
}

function seedPlaygroundFormFromSpecs(specs: PlaygroundVariableSpec[]): {
    values: Record<string, unknown>
    sent: Record<string, boolean>
} {
    const values: Record<string, unknown> = {}
    const sent: Record<string, boolean> = {}
    specs.forEach((spec) => {
        values[spec.name] = spec.defaultValue
        sent[spec.name] = spec.defaultSent
    })
    return { values, sent }
}

export enum EndpointTab {
    QUERY = 'query',
    CONFIGURATION = 'configuration',
    VERSIONS = 'versions',
    PLAYGROUND = 'playground',
    LOGS = 'logs',
    HISTORY = 'history',
}

export interface MaterializationPreview {
    can_materialize: boolean
    reason: string | null
    transformed_query: string | null
    execution_query: string | null
    display_execution_query: string | null
    range_pairs: { column: string; variables: string[]; bucket_fn: string }[]
    aggregates: { expression: string; reaggregate_fn: string | null }[]
}

export const endpointSceneLogic = kea<endpointSceneLogicType>([
    path(['products', 'endpoints', 'frontend', 'endpointSceneLogic']),
    connect(() => ({
        actions: [
            endpointLogic(),
            [
                'loadEndpoint',
                'loadEndpointSuccess',
                'loadVersions',
                'loadVersionsSuccess',
                'setEndpointDescription',
                'clearMaterializationStatus',
                'updateEndpointSuccess',
            ],
        ],
        values: [endpointLogic(), ['endpoint', 'endpointLoading', 'versions']],
    })),
    actions({
        setLocalQuery: (query: Node | null) => ({ query }),
        setActiveTab: (tab: EndpointTab) => ({ tab }),
        setPlaygroundVariableValue: (name: string, value: unknown) => ({ name, value }),
        setPlaygroundVariableSent: (name: string, sent: boolean) => ({ name, sent }),
        resetPlaygroundForm: (specs: PlaygroundVariableSpec[]) => ({ specs }),
        setPlaygroundRefresh: (refresh: EndpointRefreshMode) => ({ refresh }),
        setPlaygroundLimit: (limit: number | null) => ({ limit }),
        setPlaygroundVersion: (version: number | null) => ({ version }),
        setPlaygroundExecutionError: (error: string | null) => ({ error }),
        setDataFreshness: (dataFreshness: number) => ({ dataFreshness }),
        setIsMaterialized: (isMaterialized: boolean | null) => ({ isMaterialized }),
        setEndpointName: (name: string | null) => ({ name }),
        setViewingVersion: (version: EndpointVersionType | null) => ({ version }),
        setBucketOverride: (column: string, bucketFn: string) => ({ column, bucketFn }),
        resetBucketOverrides: (overrides: Record<string, string>) => ({ overrides }),
        toggleBreakdownOptional: (property: string) => ({ property }),
        resetOptionalBreakdownProperties: (props: string[]) => ({ props }),
        setDebugMode: (debugMode: boolean) => ({ debugMode }),
        setDebugInfoExpanded: (debugInfoExpanded: boolean) => ({ debugInfoExpanded }),
        loadMaterializationPreview: true,
        keepSqlEditorMounted: (editorTabId: string) => ({ editorTabId }),
        toggleMaterializationFromMenu: true,
    }),
    reducers({
        localQuery: [
            null as Node | null,
            {
                setLocalQuery: (_, { query }) => query,
                loadEndpointSuccess: () => null,
            },
        ],
        activeTab: [
            EndpointTab.QUERY as EndpointTab,
            {
                setActiveTab: (_, { tab }) => tab,
                loadEndpoint: () => EndpointTab.QUERY,
            },
        ],
        playgroundVariableValues: [
            {} as Record<string, unknown>,
            {
                setPlaygroundVariableValue: (state, { name, value }) => ({ ...state, [name]: value }),
                resetPlaygroundForm: (_, { specs }) => seedPlaygroundFormFromSpecs(specs).values,
                loadEndpoint: () => ({}),
            },
        ],
        playgroundVariableSent: [
            {} as Record<string, boolean>,
            {
                setPlaygroundVariableSent: (state, { name, sent }) => ({ ...state, [name]: sent }),
                resetPlaygroundForm: (_, { specs }) => seedPlaygroundFormFromSpecs(specs).sent,
                loadEndpoint: () => ({}),
            },
        ],
        playgroundRefresh: [
            'cache' as EndpointRefreshMode,
            {
                setPlaygroundRefresh: (_, { refresh }) => refresh,
                loadEndpoint: () => 'cache' as EndpointRefreshMode,
            },
        ],
        playgroundLimit: [
            null as number | null,
            {
                setPlaygroundLimit: (_, { limit }) => limit,
                loadEndpoint: () => null,
            },
        ],
        playgroundVersion: [
            null as number | null,
            {
                setPlaygroundVersion: (_, { version }) => version,
                loadEndpoint: () => null,
            },
        ],
        playgroundExecutionError: [
            null as string | null,
            {
                setPlaygroundExecutionError: (_, { error }) => error,
                loadEndpointResult: () => null,
                resetPlaygroundForm: () => null,
                loadEndpoint: () => null,
            },
        ],
        dataFreshness: [
            DEFAULT_DATA_FRESHNESS_SECONDS as number,
            {
                setDataFreshness: (_, { dataFreshness }) => dataFreshness,
                loadEndpointSuccess: (_, { endpoint }) =>
                    endpoint?.data_freshness_seconds ?? DEFAULT_DATA_FRESHNESS_SECONDS,
            },
        ],
        isMaterialized: [
            true as boolean | null,
            {
                setIsMaterialized: (_, { isMaterialized }) => isMaterialized,
                loadEndpointSuccess: (_, { endpoint }) => endpoint?.is_materialized ?? null,
                loadEndpoint: () => null,
            },
        ],
        endpointName: [
            null as string | null,
            {
                setEndpointName: (_, { name }) => name,
            },
        ],
        viewingVersion: [
            null as EndpointVersionType | null,
            {
                setViewingVersion: (_, { version }) => version,
                // Reset when switching endpoints; loadEndpointSuccess listener restores from URL if needed
                loadEndpoint: () => null,
            },
        ],
        debugMode: [
            false,
            {
                setDebugMode: (_, { debugMode }: { debugMode: boolean }) => debugMode,
                loadEndpoint: () => false,
            },
        ],
        debugInfoExpanded: [
            false,
            {
                setDebugInfoExpanded: (_, { debugInfoExpanded }: { debugInfoExpanded: boolean }) => debugInfoExpanded,
                loadEndpoint: () => false,
            },
        ],
        bucketOverrides: [
            {} as Record<string, string>,
            {
                setBucketOverride: (state, { column, bucketFn }) => ({ ...state, [column]: bucketFn }),
                resetBucketOverrides: (_, { overrides }) => overrides,
                loadEndpointSuccess: (_, { endpoint }) => endpoint?.bucket_overrides ?? {},
            },
        ],
        optionalBreakdownProperties: [
            [] as string[],
            {
                toggleBreakdownOptional: (state, { property }) =>
                    state.includes(property) ? state.filter((p) => p !== property) : [...state, property],
                resetOptionalBreakdownProperties: (_, { props }) => props,
                loadEndpointSuccess: (_, { endpoint }) => endpoint?.optional_breakdown_properties ?? [],
            },
        ],
        // Clear stale playground results when switching endpoints
        endpointResult: [
            null as string | null,
            {
                loadEndpoint: () => null,
                updateEndpointSuccess: () => null,
            },
        ],
        // Clear stale materialization preview when switching endpoints
        materializationPreview: [
            null as MaterializationPreview | null,
            {
                loadEndpoint: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        materializationPreview: {
            __default: null as MaterializationPreview | null,
            loadMaterializationPreview: async () => {
                const endpoint = values.endpoint
                if (!endpoint?.name) {
                    return null
                }
                const version = values.viewingVersion?.version
                const overrides = Object.keys(values.bucketOverrides).length > 0 ? values.bucketOverrides : undefined
                return await api.endpoint.getMaterializationPreview(endpoint.name, version, overrides)
            },
        },
        endpointResult: {
            __default: null as string | null,
            loadEndpointResult: async ({ name, data }: { name: string; data: EndpointRunRequest }) => {
                try {
                    const result = await api.endpoint.run(name, data)
                    if (result && typeof result === 'object' && 'clickhouse' in result) {
                        const { clickhouse, ...rest } = result as any
                        return JSON.stringify(rest, null, 2)
                    }
                    return JSON.stringify(result, null, 2)
                } catch (error: any) {
                    const errorResponse = {
                        error: true,
                        message: error.message || 'Unknown error',
                        status: error.status,
                        detail: error.detail || error.data,
                    }
                    return JSON.stringify(errorResponse, null, 2)
                }
            },
        },
    })),
    selectors({
        currentQuery: [
            (s) => [s.localQuery, s.endpoint, s.viewingVersion],
            (
                localQuery: Node | null,
                endpoint: EndpointType | null,
                viewingVersion: EndpointVersionType | null
            ): Node | null => localQuery || viewingVersion?.query || endpoint?.query || null,
        ],
        playgroundVariableSpecs: [
            (s) => [s.endpoint, s.viewingVersion, s.playgroundVersion, s.versions],
            (
                endpoint: EndpointType | null,
                viewingVersion: EndpointVersionType | null,
                playgroundVersion: number | null,
                versions: EndpointVersionType[] | null
            ): PlaygroundVariableSpec[] => {
                // The playground can pin a version independently of the editor's viewing version —
                // the variable contract must follow the version the request will actually run against.
                const playgroundTarget =
                    playgroundVersion !== null
                        ? ((versions ?? []).find((v) => v.version === playgroundVersion) ?? null)
                        : null
                if (playgroundTarget) {
                    return derivePlaygroundVariableSpecs(endpoint as EndpointVersionType | null, playgroundTarget)
                }
                // The endpoint payload also includes the bucket overrides, but the playground
                // form only knows about the variable contract — bucket settings live in
                // Configuration. Cast through EndpointVersionType because the runtime shape
                // includes the version-detail fields when viewingVersion is set; for the base
                // current-version case we have all the fields we need on EndpointType too.
                return derivePlaygroundVariableSpecs(endpoint as EndpointVersionType | null, viewingVersion)
            },
        ],
        playgroundPayload: [
            (s) => [
                s.playgroundVariableSpecs,
                s.playgroundVariableValues,
                s.playgroundVariableSent,
                s.playgroundRefresh,
                s.playgroundLimit,
                s.playgroundVersion,
                s.debugMode,
            ],
            (
                specs: PlaygroundVariableSpec[],
                values: Record<string, unknown>,
                sent: Record<string, boolean>,
                refresh: EndpointRefreshMode,
                limit: number | null,
                version: number | null,
                debugMode: boolean
            ): EndpointRunRequest => {
                const variables: Record<string, unknown> = {}
                specs.forEach((spec) => {
                    if (sent[spec.name]) {
                        variables[spec.name] = values[spec.name] ?? spec.defaultValue
                    }
                })
                const payload: EndpointRunRequest = {}
                if (Object.keys(variables).length > 0) {
                    payload.variables = variables as Record<string, string>
                }
                // Only emit fields that diverge from defaults — keeps the JSON preview tight.
                if (refresh && refresh !== 'cache') {
                    payload.refresh = refresh
                }
                if (limit !== null && limit !== undefined) {
                    ;(payload as any).limit = limit
                }
                if (version !== null && version !== undefined) {
                    ;(payload as any).version = version
                }
                if (debugMode) {
                    ;(payload as any).debug = true
                }
                return payload
            },
        ],
        playgroundPayloadJsonPreview: [
            (s) => [s.playgroundPayload],
            (payload: EndpointRunRequest): string => JSON.stringify(payload, null, 2),
        ],
        queryToRender: [
            (s) => [s.currentQuery],
            (currentQuery: Node | null): Node | null => {
                if (!currentQuery) {
                    return null
                }

                if (isHogQLQuery(currentQuery)) {
                    return {
                        kind: NodeKind.DataTableNode,
                        source: currentQuery,
                        showHogQLEditor: true,
                    } as DataTableNode
                }

                if (isInsightQueryNode(currentQuery)) {
                    return {
                        kind: NodeKind.InsightVizNode,
                        source: currentQuery,
                        full: true,
                    } as InsightVizNode
                }

                return currentQuery
            },
        ],
        breadcrumbs: [
            (s) => [s.endpoint],
            (endpoint: EndpointType | null): Breadcrumb[] => [
                {
                    key: Scene.Endpoints,
                    name: 'endpoints',
                    path: urls.endpoints(),
                    iconType: 'endpoints',
                },
                {
                    key: [Scene.Endpoints, endpoint?.name || 'new'],
                    name: endpoint?.name || 'New Endpoint',
                },
            ],
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        setPlaygroundVersion: ({ version }: { version: number | null }) => {
            // Keep the variable form in lockstep with the version the request will run against.
            if (version !== null && !(values.versions ?? []).some((v: EndpointVersionType) => v.version === version)) {
                if (values.endpoint?.name) {
                    actions.loadVersions(values.endpoint.name)
                }
                return // reseed happens in loadVersionsSuccess once the version is resolvable
            }
            actions.resetPlaygroundForm(values.playgroundVariableSpecs)
        },
        loadVersionsSuccess: () => {
            // Finish a playground reseed that was waiting on the versions list.
            if (values.playgroundVersion !== null) {
                actions.resetPlaygroundForm(values.playgroundVariableSpecs)
            }
        },
        keepSqlEditorMounted: ({ editorTabId }) => {
            // Already holding a mount for this editor
            if (cache.sqlEditorTabId === editorTabId) {
                return
            }
            cache.unmountSqlEditor?.()
            cache.sqlEditorTabId = editorTabId
            cache.unmountSqlEditor = sqlEditorLogic({ tabId: editorTabId, mode: SQLEditorMode.Embedded }).mount()
        },
        loadEndpoint: () => {
            cache.unmountSqlEditor?.()
            cache.unmountSqlEditor = null
            cache.sqlEditorTabId = null
        },
        loadEndpointSuccess: async ({ endpoint }: { endpoint: EndpointVersionType | null; payload?: string }) => {
            actions.resetPlaygroundForm(derivePlaygroundVariableSpecs(endpoint, null))
            actions.setDataFreshness(endpoint?.data_freshness_seconds ?? DEFAULT_DATA_FRESHNESS_SECONDS)
            actions.resetOptionalBreakdownProperties(endpoint?.optional_breakdown_properties ?? [])

            const { searchParams, hashParams } = router.values

            // Versions populate the File → Open version submenu, so always load them.
            if (endpoint?.name) {
                actions.loadVersions(endpoint.name)
            }
            if (searchParams.tab === EndpointTab.CONFIGURATION && endpoint?.name) {
                actions.loadMaterializationPreview()
            }

            // Handle version param from URL
            if (searchParams.version && endpoint?.name) {
                const versionNumber = parseInt(searchParams.version, 10)
                if (!isNaN(versionNumber) && versionNumber !== endpoint.current_version) {
                    try {
                        const versionData = await api.endpoint.get(endpoint.name, versionNumber)
                        actions.setViewingVersion(versionData)
                    } catch {
                        // Version not found, clear the param
                        const { version: _, ...nextSearchParams } = searchParams
                        router.actions.replace(urls.endpoint(endpoint.name), nextSearchParams, hashParams)
                        actions.setViewingVersion(null)
                    }
                } else {
                    // Version equals current, clear viewing version
                    actions.setViewingVersion(null)
                }
            } else {
                // No version param, clear viewing version
                actions.setViewingVersion(null)
            }
        },
        setActiveTab: ({ tab }) => {
            if (tab === EndpointTab.VERSIONS && values.endpoint?.name) {
                actions.loadVersions(values.endpoint.name)
            }
            if (tab === EndpointTab.CONFIGURATION && values.endpoint?.name) {
                actions.loadMaterializationPreview()
            }
        },
        setBucketOverride: () => {
            actions.loadMaterializationPreview()
        },
        toggleMaterializationFromMenu: () => {
            if (!values.endpoint?.name) {
                return
            }
            const baseIsMaterialized =
                values.viewingVersion?.is_materialized ?? values.endpoint?.is_materialized ?? false
            const effective = values.isMaterialized ?? baseIsMaterialized
            actions.setActiveTab(EndpointTab.CONFIGURATION)
            actions.setIsMaterialized(!effective)
            // Drive the URL so Configuration is loaded if/when LemonTabs is gone.
            const { searchParams, hashParams } = router.values
            router.actions.replace(
                urls.endpoint(values.endpoint.name),
                { ...searchParams, tab: EndpointTab.CONFIGURATION },
                hashParams
            )
        },
        setViewingVersion: ({ version }) => {
            // Reset local state so viewed version's data shows through
            actions.setLocalQuery(null)
            actions.setIsMaterialized(null)
            actions.clearMaterializationStatus()

            // Reset bucket overrides to viewed version's values
            actions.resetBucketOverrides(version?.bucket_overrides ?? values.endpoint?.bucket_overrides ?? {})

            // Reset optional breakdowns to viewed version's value (or endpoint's if going back to current)
            actions.resetOptionalBreakdownProperties(
                version?.optional_breakdown_properties ?? values.endpoint?.optional_breakdown_properties ?? []
            )

            // Reset data freshness to viewed version's value (or endpoint's if going back to current)
            actions.setDataFreshness(
                version?.data_freshness_seconds ??
                    values.endpoint?.data_freshness_seconds ??
                    DEFAULT_DATA_FRESHNESS_SECONDS
            )

            // Reset description to viewed version's description (or endpoint's if going back to current)
            if (version) {
                actions.setEndpointDescription(version.description || '')
            } else if (values.endpoint) {
                actions.setEndpointDescription(values.endpoint.description || '')
            }

            // Re-seed the playground form against the version the user is viewing.
            actions.resetPlaygroundForm(derivePlaygroundVariableSpecs(values.endpoint, version))
            // Pin the version field on the playground request if the user is viewing a non-current version.
            if (version && version.version !== values.endpoint?.current_version) {
                actions.setPlaygroundVersion(version.version)
            } else {
                actions.setPlaygroundVersion(null)
            }

            // Update URL when viewing version changes
            const { searchParams, hashParams } = router.values
            if (values.endpoint?.name) {
                const { version: _, ...nextSearchParams } = searchParams
                if (version && version.version !== values.endpoint.current_version) {
                    router.actions.replace(
                        urls.endpoint(values.endpoint.name),
                        {
                            ...nextSearchParams,
                            version: version.version,
                        },
                        hashParams
                    )
                } else {
                    // Clear version param when going back to current version
                    router.actions.replace(urls.endpoint(values.endpoint.name), nextSearchParams, hashParams)
                }
            }
        },
        loadEndpointResultSuccess: () => {
            // Mark test endpoint task as completed when user runs an endpoint in the playground
            globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.TestEndpoint)
        },
        updateEndpointSuccess: async ({ endpointName, options }) => {
            // Reload the viewed version after update to get fresh data
            const versionToReload = options?.version ?? values.viewingVersion?.version
            if (versionToReload && endpointName) {
                try {
                    const versionData = await api.endpoint.get(endpointName, versionToReload)
                    actions.setViewingVersion(versionData)
                } catch {
                    // Version may have been deleted, clear it
                    actions.setViewingVersion(null)
                }
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.endpoint(':name')]: ({ name }: { name?: string }, _, __, currentLocation, previousLocation) => {
            const { searchParams } = router.values
            const didPathChange = currentLocation.initial || currentLocation.pathname !== previousLocation?.pathname

            if (name && didPathChange) {
                const isSameEndpoint = values.endpointName === name

                if (!currentLocation.initial && isSameEndpoint) {
                    // Already viewing this endpoint, skip reload
                } else {
                    actions.setEndpointName(name)
                    actions.loadEndpoint(name)
                }
            }

            if (searchParams.tab && searchParams.tab !== values.activeTab) {
                actions.setActiveTab(searchParams.tab as EndpointTab)
            } else if (!searchParams.tab && values.activeTab !== EndpointTab.QUERY) {
                actions.setActiveTab(EndpointTab.QUERY)
            }

            // Handle version param changes without full endpoint reload
            if (!didPathChange && name) {
                const versionParam = searchParams.version ? parseInt(searchParams.version, 10) : null
                const currentViewingVersion = values.viewingVersion?.version ?? null

                if (versionParam !== currentViewingVersion) {
                    if (versionParam && values.endpoint?.name) {
                        // Load the requested version
                        const requestedVersion = versionParam
                        api.endpoint
                            .get(name, versionParam)
                            .then((versionData) => {
                                // Only apply if this is still the requested version
                                const currentParam = router.values.searchParams.version
                                if (currentParam && parseInt(currentParam, 10) === requestedVersion) {
                                    actions.setViewingVersion(versionData)
                                }
                            })
                            .catch(() => {
                                // Version not found
                                actions.setViewingVersion(null)
                            })
                    } else {
                        actions.setViewingVersion(null)
                    }
                }
            }
        },
    })),
    events(({ cache }) => ({
        beforeUnmount: () => {
            cache.unmountSqlEditor?.()
            cache.unmountSqlEditor = null
            cache.sqlEditorTabId = null
        },
    })),
])
