import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { MaxErrorTrackingSearchResponse } from '~/queries/schema/schema-assistant-error-tracking'
import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataTableNode, NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { isInsightQueryNode } from '~/queries/utils'
import { RecordingUniversalFilters } from '~/types'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { parseToolOutputRecord } from '../../../utils/toolOutput'

/**
 * Shared shape extractors for the sandbox MCP tool renderer widgets. Each turns a flattened
 * `ToolCallMessage` (built by `runStreamLogic` from ACP frames) into the props the atomic
 * `messages/*` widgets expect.
 */

function asRecord(value: unknown): Record<string, unknown> | null {
    return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function asString(value: unknown): string | undefined {
    return typeof value === 'string' ? value : undefined
}

function asPositiveSafeInteger(value: unknown): number | null {
    const parsed =
        typeof value === 'number' ? value : typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : null
    return parsed !== null && Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null
}

function asRecordArray(value: unknown): Record<string, unknown>[] | null {
    if (!Array.isArray(value)) {
        return null
    }
    const records = value.map(asRecord)
    return records.every((record): record is Record<string, unknown> => record !== null) ? records : null
}

function getAgreedPositiveSafeInteger(
    record: Record<string, unknown>,
    keys: readonly string[]
): number | null | undefined {
    const values = keys.filter((key) => key in record).map((key) => asPositiveSafeInteger(record[key]))
    if (values.length === 0) {
        return undefined
    }
    if (values.some((value) => value === null)) {
        return null
    }
    return values.every((value) => value === values[0]) ? values[0]! : null
}

function getRequestDashboardId(input: Record<string, unknown>): number | null {
    return getAgreedPositiveSafeInteger(input, ['id', 'dashboard_id', 'dashboardId']) ?? null
}

function responseAgreesWithDashboard(output: Record<string, unknown>, dashboardId: number): boolean {
    const directDashboardId = getAgreedPositiveSafeInteger(output, ['dashboard_id', 'dashboardId'])
    if (directDashboardId === null || (directDashboardId !== undefined && directDashboardId !== dashboardId)) {
        return false
    }

    const nestedDashboard = asRecord(output.dashboard)
    if (!nestedDashboard) {
        return true
    }
    return getAgreedPositiveSafeInteger(nestedDashboard, ['id']) === dashboardId
}

function getResponseTileId(output: Record<string, unknown>, dashboardId: number): number | null {
    if (!responseAgreesWithDashboard(output, dashboardId)) {
        return null
    }
    return getAgreedPositiveSafeInteger(output, ['id', 'tile_id']) ?? null
}

function getDashboardIdFromPostHogUrl(value: unknown): number | null {
    if (typeof value !== 'string') {
        return null
    }
    try {
        const url = new URL(value)
        if ((url.protocol !== 'http:' && url.protocol !== 'https:') || !url.hostname) {
            return null
        }
        const match = /^\/project\/(\d+)\/dashboard\/(\d+)\/?$/.exec(url.pathname)
        if (!match || asPositiveSafeInteger(match[1]) === null) {
            return null
        }
        return asPositiveSafeInteger(match[2])
    } catch {
        return null
    }
}

export interface DashboardRevealTarget {
    dashboardId: number
    tileId?: number
    insightShortId?: string
}

const DASHBOARD_TILE_CREATE_KEYS = new Set(['dashboard-create-tile', 'dashboard-create-text-tile'])
const DASHBOARD_TILE_UPDATE_KEYS = new Set(['dashboard-update-text-tile'])
const DASHBOARD_BATCH_ADD_KEYS = new Set(['dashboard-widgets-batch-add', 'dashboards-widgets-batch-create'])
const DASHBOARD_BATCH_UPDATE_KEYS = new Set(['dashboard-widgets-batch-update'])
const DASHBOARD_RESPONSE_KEYS = new Set([
    'dashboard-update',
    'dashboard-reorder-tiles',
    'dashboard-tile-copy',
    'dashboards-copy-tile-create',
    'dashboards-move-tile-create',
    'dashboards-move-tile-partial-update',
])

function extractDashboardBatchRevealTarget(
    input: Record<string, unknown>,
    output: Record<string, unknown>,
    dashboardId: number,
    requireExistingTileIds: boolean
): DashboardRevealTarget | null {
    const requestedWidgets = asRecordArray(input.widgets)
    const returnedTiles = asRecordArray(output.tiles)
    if (
        !requestedWidgets ||
        !returnedTiles ||
        requestedWidgets.length === 0 ||
        requestedWidgets.length !== returnedTiles.length
    ) {
        return null
    }

    const tileIds = returnedTiles.map((tile) => getResponseTileId(tile, dashboardId))
    if (tileIds.some((tileId) => tileId === null)) {
        return null
    }

    if (requireExistingTileIds) {
        const requestedTileIds = requestedWidgets.map((widget) => getAgreedPositiveSafeInteger(widget, ['tile_id']))
        if (
            requestedTileIds.some((tileId) => tileId === null || tileId === undefined) ||
            requestedTileIds.some((tileId, index) => tileId !== tileIds[index])
        ) {
            return null
        }
    }

    return tileIds.length === 1 ? { dashboardId, tileId: tileIds[0]! } : { dashboardId }
}

/**
 * Produces a navigation target only when the completed mutation response corroborates the request.
 * Ambiguous batches and response/request disagreements intentionally fall back to the generic card.
 */
export function extractDashboardMutationRevealTarget(message: ToolCallMessage): DashboardRevealTarget | null {
    if (message.status !== 'completed') {
        return null
    }
    const input = asRecord(message.innerInput)
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    if (!input || !output) {
        return null
    }
    const dashboardId = getRequestDashboardId(input)
    if (dashboardId === null) {
        return null
    }

    if (DASHBOARD_TILE_CREATE_KEYS.has(message.resolvedKey)) {
        const tileId = getResponseTileId(output, dashboardId)
        return tileId === null ? null : { dashboardId, tileId }
    }

    if (DASHBOARD_TILE_UPDATE_KEYS.has(message.resolvedKey)) {
        const requestedTileId = getAgreedPositiveSafeInteger(input, ['tile_id'])
        const responseTileId = getResponseTileId(output, dashboardId)
        return requestedTileId === null || requestedTileId === undefined || requestedTileId !== responseTileId
            ? null
            : { dashboardId, tileId: responseTileId }
    }

    if (DASHBOARD_BATCH_ADD_KEYS.has(message.resolvedKey)) {
        return extractDashboardBatchRevealTarget(input, output, dashboardId, false)
    }

    if (DASHBOARD_BATCH_UPDATE_KEYS.has(message.resolvedKey)) {
        return extractDashboardBatchRevealTarget(input, output, dashboardId, true)
    }

    if (message.resolvedKey === 'dashboard-delete-tile') {
        return getDashboardIdFromPostHogUrl(output._posthogUrl) === dashboardId ? { dashboardId } : null
    }

    if (DASHBOARD_RESPONSE_KEYS.has(message.resolvedKey)) {
        return getAgreedPositiveSafeInteger(output, ['id']) === dashboardId ? { dashboardId } : null
    }

    return null
}

/**
 * Intersects a requested dashboard with the saved insight's authoritative, non-deleted tile response.
 * Request-side dashboard IDs alone never establish a reveal target.
 */
export function extractInsightDashboardRevealTarget(message: ToolCallMessage): DashboardRevealTarget | null {
    if (
        message.status !== 'completed' ||
        (message.resolvedKey !== 'insight-create' && message.resolvedKey !== 'insight-update')
    ) {
        return null
    }
    const input = asRecord(message.innerInput)
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    const requestedDashboards = input && Array.isArray(input.dashboards) ? input.dashboards : null
    const shortId = asString(output?.short_id)
    const dashboardTiles = asRecordArray(output?.dashboard_tiles)
    if (
        !requestedDashboards ||
        requestedDashboards.length !== 1 ||
        !shortId?.trim() ||
        !dashboardTiles ||
        dashboardTiles.length === 0
    ) {
        return null
    }

    const dashboardId = asPositiveSafeInteger(requestedDashboards[0])
    if (dashboardId === null) {
        return null
    }
    const matchingTiles = dashboardTiles.filter(
        (tile) =>
            asPositiveSafeInteger(tile.dashboard_id) === dashboardId &&
            (tile.deleted === false || tile.deleted === null)
    )
    if (matchingTiles.length !== 1) {
        return null
    }
    const tileId = asPositiveSafeInteger(matchingTiles[0].id)
    return tileId === null ? null : { dashboardId, tileId, insightShortId: shortId }
}

const QUERY_WRAPPER_KIND_BY_TOOL_KEY: Record<string, NodeKind> = {
    'query-trends': NodeKind.TrendsQuery,
    'query-funnel': NodeKind.FunnelsQuery,
    'query-retention': NodeKind.RetentionQuery,
    'query-stickiness': NodeKind.StickinessQuery,
    'query-paths': NodeKind.PathsQuery,
    'query-lifecycle': NodeKind.LifecycleQuery,
    'query-llm-traces-list': NodeKind.TracesQuery,
    'query-trends-actors': NodeKind.InsightActorsQuery,
    'query-lifecycle-actors': NodeKind.InsightActorsQuery,
    'query-paths-actors': NodeKind.InsightActorsQuery,
    'query-retention-actors': NodeKind.InsightActorsQuery,
}

function queryFromToolInput(message: ToolCallMessage): Record<string, unknown> | null {
    const input = asRecord(message.innerInput)
    if (!input) {
        return null
    }

    const query = { ...input }
    delete query.output_format

    if (typeof query.kind === 'string') {
        return query
    }

    const inferredKind = QUERY_WRAPPER_KIND_BY_TOOL_KEY[message.resolvedKey]
    return inferredKind ? { ...query, kind: inferredKind } : null
}

/** The artifact envelope + content the visualization widget proxies consume. */
export interface VisualizationArtifactExtraction {
    envelope: ArtifactMessage
    content: VisualizationArtifactContent
}

/**
 * Pulls a `VisualizationArtifactContent` out of an insight tool's `rawOutput`. The backend MCP
 * server returns the artifact directly in the existing schema shape. Saved insights
 * (create / update / get) carry a `short_id` in the REST payload (or an explicit `artifact_id`);
 * query-only outputs carry neither and render inline as ephemeral visualizations.
 */
export function extractVisualizationArtifact(message: ToolCallMessage): VisualizationArtifactExtraction | null {
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    if (!output) {
        return null
    }

    const query = output.query
    if (!query) {
        return null
    }

    const artifactId = asString(output.artifact_id) ?? asString(output.short_id) ?? message.id
    const isSaved = asString(output.short_id) !== undefined || asString(output.artifact_id) !== undefined
    const source = isSaved ? ArtifactSource.Insight : ArtifactSource.State

    const content: VisualizationArtifactContent = {
        content_type: ArtifactContentType.Visualization,
        query: query as VisualizationArtifactContent['query'],
        name: asString(output.name) ?? asString(message.innerInput?.name) ?? null,
        description: asString(output.description) ?? null,
    }

    const envelope: ArtifactMessage = {
        type: AssistantMessageType.Artifact,
        id: message.id,
        artifact_id: artifactId,
        source,
        content,
    }

    return { envelope, content }
}

/** A query-wrapper tool result mapped onto renderable visualization content. */
export interface QueryResultExtraction {
    content: VisualizationArtifactContent
    /** The MCP server's `_posthogUrl` enrichment — the "open as insight" CTA target. */
    url: string | null
}

/**
 * Maps a query-wrapper tool's output (`{query, results, _posthogUrl}`) onto visualization
 * content. Insight queries pass through bare (the widget wraps them in `InsightVizNode`);
 * table-renderable kinds are wrapped in a `DataTableNode` here. Kinds without an inline
 * renderer (e.g. a single LLM trace) return null and fall back to the generic card.
 */
export function extractQueryResult(message: ToolCallMessage): QueryResultExtraction | null {
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    const query = (output ? asRecord(output.query) : null) ?? queryFromToolInput(message)
    if (!query || typeof query.kind !== 'string') {
        return null
    }

    let renderable: VisualizationArtifactContent['query'] | null = null
    if (isInsightQueryNode(query)) {
        renderable = query as VisualizationArtifactContent['query']
    } else if (query.kind === NodeKind.TracesQuery || query.kind === NodeKind.ActorsQuery) {
        // The actors wrappers echo a ready-made ActorsQuery envelope; traces come back bare.
        renderable = { kind: NodeKind.DataTableNode, source: query } as unknown as DataTableNode
    } else if (query.kind === NodeKind.InsightActorsQuery) {
        // Defensive: a bare InsightActorsQuery isn't a table source — wrap it in an ActorsQuery first.
        renderable = {
            kind: NodeKind.DataTableNode,
            source: { kind: NodeKind.ActorsQuery, source: query, select: ['actor'] },
        } as unknown as DataTableNode
    }

    if (!renderable) {
        return null
    }

    return {
        content: {
            content_type: ArtifactContentType.Visualization,
            query: renderable,
            name: null,
            description: null,
        },
        url: asString(output?._posthogUrl) ?? null,
    }
}

/** Dashboard create/update output — the REST payload (`id`, `name`) plus the MCP server's `_posthogUrl` enrichment. */
export interface DashboardExtraction {
    id?: string | number
    name?: string
    url?: string
}

export function extractDashboard(message: ToolCallMessage): DashboardExtraction | null {
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    if (!output) {
        return null
    }
    const id = (output.id ?? output.dashboard_id) as string | number | undefined
    return {
        id,
        name: asString(output.name) ?? asString(message.innerInput?.name),
        url: asString(output._posthogUrl) ?? asString(output.url),
    }
}

/**
 * Resolves the `RecordingUniversalFilters` the playlist widget renders. The query-wrapper tool
 * echoes the executed `RecordingsQuery` back under `rawOutput.query`, which we convert; a
 * ready-made universal filters object under `rawOutput.filters` is passed through. Anything else
 * falls back to the generic card rather than feeding the playlist a shape it can't use.
 */
export function extractRecordingFilters(message: ToolCallMessage): RecordingUniversalFilters | null {
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    if (!output) {
        return null
    }

    const directFilters = asRecord(output.filters)
    if (directFilters && 'filter_group' in directFilters && Array.isArray(directFilters.duration)) {
        return directFilters as unknown as RecordingUniversalFilters
    }

    const query = asRecord(output.query)
    if (query && query.kind === NodeKind.RecordingsQuery) {
        const recordingsQuery = query as unknown as RecordingsQuery
        // The shared converter intentionally drops list-level fields (its caller manages them
        // separately) — carry them over so the widget reflects what the agent actually searched.
        return {
            ...recordingsQueryToUniversalFilters(recordingsQuery),
            date_from: recordingsQuery.date_from ?? null,
            date_to: recordingsQuery.date_to ?? null,
            order: recordingsQuery.order,
            order_direction: recordingsQuery.order_direction,
            limit: recordingsQuery.limit,
            session_ids: recordingsQuery.session_ids,
        }
    }

    return null
}

const ERROR_TRACKING_RESPONSE_KEYS: readonly (keyof MaxErrorTrackingSearchResponse)[] = [
    'issues',
    'search_query',
    'status',
    'date_from',
    'order_by',
]

/**
 * Error-tracking search output is a `MaxErrorTrackingSearchResponse` (a filters echo plus issue
 * previews) for `ErrorTrackingFiltersWidget`. Outputs that carry none of its fields — e.g. a raw
 * REST issues list — fall back to the generic card instead of rendering empty filter chips.
 */
export function extractErrorTrackingResponse(message: ToolCallMessage): MaxErrorTrackingSearchResponse | null {
    const output = parseToolOutputRecord(message.rawOutput, message.rawInput)
    if (!output || !ERROR_TRACKING_RESPONSE_KEYS.some((key) => key in output)) {
        return null
    }
    return output as MaxErrorTrackingSearchResponse
}
