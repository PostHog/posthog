import { recordingsQueryToUniversalFilters } from 'scenes/session-recordings/filters/recordingsQueryConversions'

import {
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    AssistantMessageType,
    VisualizationArtifactContent,
} from '~/queries/schema/schema-assistant-messages'
import { DataTableNode, NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import {
    isDataTableNode,
    isDataVisualizationNode,
    isHogQLQuery,
    isInsightQueryNode,
    isInsightVizNode,
} from '~/queries/utils'
import { RecordingUniversalFilters } from '~/types'

import type { ToolCallMessage } from 'products/posthog_ai/frontend/types/toolTypes'

import { getToolOutputRecord } from '../getToolOutputRecord'

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
    const output = getToolOutputRecord(message)
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
    const output = getToolOutputRecord(message)
    const query = asRecord(output?.query)
    if (!query || typeof query.kind !== 'string') {
        return null
    }

    let renderable: VisualizationArtifactContent['query'] | null = null
    if (
        isInsightQueryNode(query) ||
        isHogQLQuery(query) ||
        (isInsightVizNode(query) && isInsightQueryNode(query.source)) ||
        (isDataVisualizationNode(query) && isHogQLQuery(query.source)) ||
        // A saved table insight arrives as a bare node; its source can be any table-readable kind.
        (isDataTableNode(query) && typeof asRecord(query.source)?.kind === 'string')
    ) {
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

    const insight = asRecord(output?.insight)
    return {
        content: {
            content_type: ArtifactContentType.Visualization,
            query: renderable,
            name: asString(insight?.name) ?? null,
            description: asString(insight?.description) ?? null,
        },
        url: asString(output?._posthogUrl) ?? asString(insight?.url) ?? null,
    }
}

/** Dashboard create/update output — the REST payload (`id`, `name`) plus the MCP server's `_posthogUrl` enrichment. */
export interface DashboardExtraction {
    id?: string | number
    name?: string
    url?: string
}

export function extractDashboard(message: ToolCallMessage): DashboardExtraction | null {
    const output = getToolOutputRecord(message)
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
    const output = getToolOutputRecord(message)
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
