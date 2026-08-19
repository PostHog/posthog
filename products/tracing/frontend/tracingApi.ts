import { ApiConfig } from 'lib/api'

import { AggregatedSpanRow, SpanTreeNode } from '~/queries/schema/schema-general'

import {
    tracingSpansAggregateCreate,
    tracingSpansCountCreate,
    tracingSpansDurationHistogramCreate,
    tracingSpansHasSpansRetrieve,
    tracingSpansLatencyHeatmapCreate,
    tracingSpansQueryCreate,
    tracingSpansServiceNamesRetrieve,
    tracingSpansSparklineCreate,
    tracingSpansTraceCreate,
    tracingSpansTreeCreate,
} from './generated/api'

// nosemgrep: prefer-codegen-api
const projectId = (): string => String(ApiConfig.getCurrentProjectId())

const requestOptions = (signal?: AbortSignal): RequestInit | undefined => (signal ? { signal } : undefined)

export const tracingApi = {
    async hasSpans(): Promise<boolean> {
        return Boolean((await tracingSpansHasSpansRetrieve(projectId())).hasSpans)
    },
    async listSpans(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: Record<string, any>[]; hasMore: boolean; nextCursor?: string }> {
        return (await tracingSpansQueryCreate(
            projectId(),
            { query } as Parameters<typeof tracingSpansQueryCreate>[1],
            requestOptions(signal)
        )) as { results: Record<string, any>[]; hasMore: boolean; nextCursor?: string }
    },
    async getTrace(
        traceId: string,
        query?: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: Record<string, any>[]; hasMore: boolean; nextOffset?: number | null }> {
        return (await tracingSpansTraceCreate(
            projectId(),
            traceId,
            { ...query, dateRange: query?.dateRange ?? { date_from: '-24h' } },
            requestOptions(signal)
        )) as { results: Record<string, any>[]; hasMore: boolean; nextOffset?: number | null }
    },
    async sparkline(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: { time: string; service: string; count: number }[] }> {
        return (await tracingSpansSparklineCreate(projectId(), { query }, requestOptions(signal))) as {
            results: { time: string; service: string; count: number }[]
        }
    },
    async count(query: Record<string, any>, signal?: AbortSignal): Promise<{ count: number; traceCount: number }> {
        return await tracingSpansCountCreate(projectId(), { query }, requestOptions(signal))
    },
    async durationHistogram(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: { bucket_ns: number; service: string; count: number }[] }> {
        return (await tracingSpansDurationHistogramCreate(projectId(), { query }, requestOptions(signal))) as {
            results: { bucket_ns: number; service: string; count: number }[]
        }
    },
    async latencyHeatmap(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: { time: string; bucket_ns: number; count: number }[] }> {
        return await tracingSpansLatencyHeatmapCreate(projectId(), { query }, requestOptions(signal))
    },
    async aggregate(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{
        results: AggregatedSpanRow[]
        compare?: AggregatedSpanRow[] | null
        has_more?: boolean
        next_offset?: number | null
    }> {
        return (await tracingSpansAggregateCreate(projectId(), { query }, requestOptions(signal))) as {
            results: AggregatedSpanRow[]
            compare?: AggregatedSpanRow[] | null
            has_more?: boolean
            next_offset?: number | null
        }
    },
    async tree(
        query: Record<string, any>,
        signal?: AbortSignal
    ): Promise<{ results: SpanTreeNode[]; compare?: SpanTreeNode[] | null }> {
        return (await tracingSpansTreeCreate(
            projectId(),
            { query } as Parameters<typeof tracingSpansTreeCreate>[1],
            requestOptions(signal)
        )) as {
            results: SpanTreeNode[]
            compare?: SpanTreeNode[] | null
        }
    },
    async serviceNames(params: { dateRange?: string; search?: string }): Promise<{ results: { name: string }[] }> {
        const response = await tracingSpansServiceNamesRetrieve(projectId(), params)
        return { results: response.results.map((name) => ({ name })) }
    },
}
