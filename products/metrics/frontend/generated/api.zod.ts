/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { _MetricAnomalyRequestApi, _MetricQueryRequestApi, _MetricSamplesRequestApi } from './api.zod.schemas'

/**
 * Characterize a metric anomaly: compare an anomaly window against a
 * baseline, find the onset, and rank which label values moved.
 */
export const MetricsCharacterizeCreateBody = _MetricAnomalyRequestApi

export const MetricsQueryCreateBody = _MetricQueryRequestApi

/**
 * Raw individual emissions for a metric (the events model), newest
 * first — backs the Samples view and the metric->trace pivot.
 */
export const MetricsSamplesCreateBody = _MetricSamplesRequestApi
