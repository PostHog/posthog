/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import {
    PatchedTracingViewApi,
    TracingViewApi,
    _SymbolStatsRequestApi,
    _TracingAggregationRequestApi,
    _TracingAttributeBreakdownRequestApi,
    _TracingCountRequestApi,
    _TracingDurationHistogramRequestApi,
    _TracingLatencyHeatmapRequestApi,
    _TracingQueryRequestApi,
    _TracingSparklineRequestApi,
    _TracingTraceRequestApi,
    _TracingTreeRequestApi,
} from './api.zod.schemas'

export const TracingSpansAggregateCreateBody = _TracingAggregationRequestApi

export const TracingSpansAttributeBreakdownCreateBody = _TracingAttributeBreakdownRequestApi

export const TracingSpansCountCreateBody = _TracingCountRequestApi

export const TracingSpansDurationHistogramCreateBody = _TracingDurationHistogramRequestApi

export const TracingSpansLatencyHeatmapCreateBody = _TracingLatencyHeatmapRequestApi

export const TracingSpansQueryCreateBody = _TracingQueryRequestApi

export const TracingSpansSparklineCreateBody = _TracingSparklineRequestApi

export const TracingSpansSymbolStatsCreateBody = _SymbolStatsRequestApi

export const TracingSpansTraceCreateBody = _TracingTraceRequestApi

export const TracingSpansTreeCreateBody = _TracingTreeRequestApi

export const TracingViewsCreateBody = TracingViewApi

export const TracingViewsUpdateBody = TracingViewApi

export const TracingViewsPartialUpdateBody = PatchedTracingViewApi
