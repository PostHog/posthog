/**
 * Auto-generated Zod validation schemas from the Django backend OpenAPI schema.
 * To modify these schemas, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
import { z as zod } from 'zod'

export const AppMetricSeriesApi = zod.object({
    name: zod.string(),
    values: zod.array(zod.number()),
})

export type AppMetricSeriesApi = zod.input<typeof AppMetricSeriesApi>
export type AppMetricSeriesApiOutput = zod.output<typeof AppMetricSeriesApi>

export const AppMetricsResponseApi = zod.object({
    labels: zod.array(zod.string()),
    series: zod.array(
        zod.object({
            name: zod.string(),
            values: zod.array(zod.number()),
        })
    ),
})

export type AppMetricsResponseApi = zod.input<typeof AppMetricsResponseApi>
export type AppMetricsResponseApiOutput = zod.output<typeof AppMetricsResponseApi>

export const AppMetricsTotalsResponseApi = zod.object({
    totals: zod.record(zod.string(), zod.number()),
})

export type AppMetricsTotalsResponseApi = zod.input<typeof AppMetricsTotalsResponseApi>
export type AppMetricsTotalsResponseApiOutput = zod.output<typeof AppMetricsTotalsResponseApi>
