/**
 * Prometheus metrics emitted by the v2026 pipeline.
 *
 * Co-located with the pipeline to keep the legacy `metrics.ts` from drifting.
 * Anything observed about the new protocol lives here.
 */

import { Counter, Histogram } from 'prom-client'

/**
 * One increment per dispatched v2026 `tools/call`. `outcome` distinguishes
 * a `complete` result from an `input_required` round-trip from an error
 * response.
 */
export const v2026RequestsTotal = new Counter({
    name: 'mcp_v2026_requests_total',
    help: 'Total requests dispatched by the v2026 MCP pipeline.',
    labelNames: ['outcome'] as const,
})

/**
 * Every decode of an incoming `requestState`. `result=ok` is the happy path;
 * the other labels match `RequestStateError.metricLabel` for direct
 * traceability between code and metric.
 */
export const v2026RequestStateDecodeTotal = new Counter({
    name: 'mcp_v2026_request_state_decode_total',
    help: 'Outcomes of decoding inbound v2026 requestState tokens.',
    labelNames: ['result'] as const,
})

/**
 * Dedicated counter for the expiry case — sustained non-zero rate is the
 * signal that `REQUEST_STATE_TTL_SECONDS` is too tight for real user
 * latency. Refining via this one signal keeps the TTL tunable from the
 * dashboard.
 */
export const v2026RequestStateExpiredTotal = new Counter({
    name: 'mcp_v2026_request_state_expired_total',
    help: 'Inbound v2026 requestState tokens rejected because they were past their exp claim.',
})

/**
 * How many `InputRequiredResult` rounds a single logical tool call took
 * before producing a `complete` result. 1 is the typical case (one elicit,
 * one retry).
 */
export const v2026InputRequiredRoundTrips = new Histogram({
    name: 'mcp_v2026_input_required_round_trips',
    help: 'Distribution of InputRequiredResult rounds per logical v2026 tool call.',
    buckets: [1, 2, 3, 5, 8, 10],
})
