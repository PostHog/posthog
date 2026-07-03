/**
 * Regression tests for the experiment-results-get response transformation.
 *
 * Production trace: an agent calling `experiment-results-get` couldn't tell
 * which secondary-metric row belonged to which metric (`data.metric` was null)
 * and concluded `metrics_secondary: []` meant no secondaries, when in fact every
 * secondary was attached as a shared metric.
 *
 * These tests pin the contract:
 *  - each result row carries a self-describing `metric` summary
 *  - inline and shared metrics are merged into one ordered result stream,
 *    with `source` tagged so callers can tell them apart
 *  - row order follows `*_metrics_ordered_uuids` (the canonical UI ordering)
 *  - UI-only bulk fields (`clickhouse_sql`, `hogql`, `insight`, and
 *    `step_sessions` — including the copies inside each `breakdown_results`
 *    entry) are stripped from each row's `data`, while statistical fields
 *    (including per-breakdown stats) are preserved
 */
import { describe, expect, it } from 'vitest'

import type { Experiment } from '@/schema/experiments'
import {
    buildMetricEntries,
    ExperimentExposureQuerySchema,
    ExperimentSchema,
    transformExperimentResults,
} from '@/schema/experiments'

const baseExposures = {
    kind: 'ExperimentExposureQuery' as const,
    timeseries: [],
    total_exposures: {},
    date_range: { date_from: '2026-01-01T00:00:00Z', date_to: null as string | null },
}

// Parse rather than cast so the factory stays honest if ExperimentSchema gains
// required fields — a missing field fails the test instead of silently typing.
const makeExperiment = (overrides: Partial<Experiment>): Experiment =>
    ExperimentSchema.parse({
        id: 1,
        name: 'Test',
        feature_flag_key: 'k',
        archived: false,
        deleted: false,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        saved_metrics_ids: null,
        ...overrides,
    })

describe('transformExperimentResults', () => {
    it('attaches metric metadata to each result row so callers do not need a second experiment-get', () => {
        const experiment = makeExperiment({
            metrics: [{ uuid: 'p-1', name: 'Primary', metric_type: 'mean', goal: 'increase' }],
            metrics_secondary: [{ uuid: 's-1', name: 'Secondary', metric_type: 'funnel', goal: 'decrease' }],
            primary_metrics_ordered_uuids: ['p-1'],
            secondary_metrics_ordered_uuids: ['s-1'],
        })
        const primaryEntries = buildMetricEntries(experiment, 'primary')
        const secondaryEntries = buildMetricEntries(experiment, 'secondary')

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: primaryEntries,
            secondaryMetricEntries: secondaryEntries,
            primaryMetricsResults: [{ baseline: { key: 'control' } }],
            secondaryMetricsResults: [{ baseline: { key: 'control' } }],
        })

        expect(result.metrics.primary.results[0]?.metric).toEqual({
            uuid: 'p-1',
            name: 'Primary',
            metric_type: 'mean',
            goal: 'increase',
            source: 'inline',
            saved_metric_id: null,
            saved_metric_name: null,
        })
        expect(result.metrics.secondary.results[0]?.metric).toEqual({
            uuid: 's-1',
            name: 'Secondary',
            metric_type: 'funnel',
            goal: 'decrease',
            source: 'inline',
            saved_metric_id: null,
            saved_metric_name: null,
        })
    })

    it('treats inline and shared metrics as one ordered surface and tags the source on each', () => {
        const experiment = makeExperiment({
            metrics: [],
            metrics_secondary: [{ uuid: 'inline-1', name: 'Inline secondary', metric_type: 'mean' }],
            saved_metrics: [
                {
                    saved_metric: 42,
                    name: 'Shared secondary',
                    metadata: { type: 'secondary' },
                    query: { uuid: 'shared-1', name: 'Shared query', metric_type: 'funnel', goal: 'increase' },
                },
            ],
            secondary_metrics_ordered_uuids: ['inline-1', 'shared-1'],
        })
        const entries = buildMetricEntries(experiment, 'secondary')

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: [],
            secondaryMetricEntries: entries,
            primaryMetricsResults: [],
            secondaryMetricsResults: [{ baseline: { key: 'control' } }, { baseline: { key: 'control' } }],
        })

        expect(result.metrics.secondary.results).toHaveLength(2)
        expect(result.metrics.secondary.results[0]?.metric).toEqual(
            expect.objectContaining({
                uuid: 'inline-1',
                name: 'Inline secondary',
                source: 'inline',
                saved_metric_id: null,
                saved_metric_name: null,
            })
        )
        expect(result.metrics.secondary.results[1]?.metric).toEqual(
            expect.objectContaining({
                uuid: 'shared-1',
                source: 'shared',
                saved_metric_id: 42,
                saved_metric_name: 'Shared secondary',
            })
        )
    })

    it("uses the saved metric's UI label as `name` on shared rows (not the inner query.name)", () => {
        // The saved metric's `name` is what users see in the experiment UI; the inner
        // `query.name` is internal and may be unset or drifted. An agent asked "which
        // metric is this?" should reach for `summary.name` and get the UI label.
        const experiment = makeExperiment({
            saved_metrics: [
                {
                    saved_metric: 1,
                    name: 'Activation funnel (revenue impact)',
                    metadata: { type: 'primary' },
                    query: { uuid: 'shared-x', name: 'inner_funnel_v2', metric_type: 'funnel' },
                },
            ],
            primary_metrics_ordered_uuids: ['shared-x'],
        })
        const [entry] = buildMetricEntries(experiment, 'primary')
        expect(entry?.summary.name).toBe('Activation funnel (revenue impact)')
        expect(entry?.summary.saved_metric_name).toBe('Activation funnel (revenue impact)')
    })

    it('orders result rows by *_metrics_ordered_uuids (the canonical UI ordering)', () => {
        // Insertion order puts the inline metric first; ordered_uuids puts the shared one
        // first. Without the sort step, an agent reading top-to-bottom would see a
        // different order than what users see in the experiment UI.
        const experiment = makeExperiment({
            metrics_secondary: [{ uuid: 'inline-a', name: 'Inline A', metric_type: 'mean' }],
            saved_metrics: [
                {
                    saved_metric: 7,
                    name: 'Shared B',
                    metadata: { type: 'secondary' },
                    query: { uuid: 'shared-b', name: 'Shared B', metric_type: 'mean' },
                },
            ],
            secondary_metrics_ordered_uuids: ['shared-b', 'inline-a'],
        })
        const entries = buildMetricEntries(experiment, 'secondary')

        expect(entries.map((e) => e.summary.uuid)).toEqual(['shared-b', 'inline-a'])
    })

    it('skips saved metrics with a missing or unexpected metadata.type instead of defaulting them', () => {
        // A defensive guard: a malformed secondary metric must not silently surface in
        // the primary slot. Better to drop than to misclassify.
        const experiment = makeExperiment({
            saved_metrics: [
                { saved_metric: 1, name: 'No type', metadata: {}, query: { uuid: 'no-type', metric_type: 'mean' } },
                {
                    saved_metric: 2,
                    name: 'Bogus type',
                    metadata: { type: 'tertiary' },
                    query: { uuid: 'bogus', metric_type: 'mean' },
                },
                {
                    saved_metric: 3,
                    name: 'Good primary',
                    metadata: { type: 'primary' },
                    query: { uuid: 'good-primary', metric_type: 'mean' },
                },
            ],
        })
        expect(buildMetricEntries(experiment, 'primary').map((e) => e.summary.uuid)).toEqual(['good-primary'])
        expect(buildMetricEntries(experiment, 'secondary')).toEqual([])
    })

    it('preserves experiment.metrics, metrics_secondary, and saved_metrics on the response so callers can audit the source surfaces', () => {
        const inlineMetric = { uuid: 'p-1', name: 'Primary', metric_type: 'mean' }
        const inlineSecondary = { uuid: 's-1', name: 'Secondary', metric_type: 'mean' }
        const savedMetric = {
            saved_metric: 9,
            name: 'Shared',
            metadata: { type: 'primary' as const },
            query: { uuid: 'shared-9', metric_type: 'mean' },
        }
        const experiment = makeExperiment({
            metrics: [inlineMetric],
            metrics_secondary: [inlineSecondary],
            saved_metrics: [savedMetric],
            primary_metrics_ordered_uuids: ['p-1', 'shared-9'],
            secondary_metrics_ordered_uuids: ['s-1'],
        })

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: buildMetricEntries(experiment, 'primary'),
            secondaryMetricEntries: buildMetricEntries(experiment, 'secondary'),
            primaryMetricsResults: [{ baseline: { key: 'control' } }, { baseline: { key: 'control' } }],
            secondaryMetricsResults: [{ baseline: { key: 'control' } }],
        })

        expect(result.experiment.metrics).toEqual([inlineMetric])
        expect(result.experiment.metrics_secondary).toEqual([inlineSecondary])
        expect(result.experiment.saved_metrics).toEqual([savedMetric])
    })

    it('keeps a row with `data: null` when the underlying metric query fails, so positions stay aligned', () => {
        // The API client returns `null` for that row when the per-metric query errors.
        // Erasing the row would shift subsequent positions away from
        // primary_metrics_ordered_uuids, making "the third metric" ambiguous to callers.
        const experiment = makeExperiment({
            metrics: [
                { uuid: 'p-1', name: 'Worked', metric_type: 'mean' },
                { uuid: 'p-2', name: 'Failed', metric_type: 'mean' },
                { uuid: 'p-3', name: 'Worked too', metric_type: 'mean' },
            ],
            primary_metrics_ordered_uuids: ['p-1', 'p-2', 'p-3'],
        })

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: buildMetricEntries(experiment, 'primary'),
            secondaryMetricEntries: [],
            primaryMetricsResults: [{ baseline: { key: 'control' } }, null, { baseline: { key: 'control' } }],
            secondaryMetricsResults: [],
        })

        expect(result.metrics.primary.count).toBe(3)
        expect(result.metrics.primary.results).toHaveLength(3)
        expect(result.metrics.primary.results[1]?.data).toBeNull()
        expect(result.metrics.primary.results[1]?.metric.uuid).toBe('p-2')
        expect(result.metrics.primary.results[1]?.metric.name).toBe('Failed')
        expect(result.metrics.primary.results.map((r) => r.metric.uuid)).toEqual(['p-1', 'p-2', 'p-3'])
    })

    it('strips UI-only bulk fields (SQL bodies, step_sessions) but keeps statistical data', () => {
        // step_sessions is only used by the frontend's funnel step-bar, MCP callers can't
        // act on those event ids. clickhouse_sql / hogql are also debug-only. Strip both,
        // keep statistical fields intact.
        const experiment = makeExperiment({
            metrics: [{ uuid: 'p-1', name: 'Primary', metric_type: 'funnel' }],
            primary_metrics_ordered_uuids: ['p-1'],
        })
        const longSql = 'SELECT * FROM events WHERE 1=1'.repeat(2000)
        const stepSessions = [
            Array.from({ length: 100 }, (_, i) => ({ event_uuid: `e-${i}`, session_id: `s-${i}` })),
            Array.from({ length: 100 }, (_, i) => ({ event_uuid: `e2-${i}`, session_id: `s2-${i}` })),
        ]

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: buildMetricEntries(experiment, 'primary'),
            secondaryMetricEntries: [],
            primaryMetricsResults: [
                {
                    baseline: {
                        key: 'control',
                        sum: 100,
                        sum_squares: 100,
                        step_counts: [100, 50],
                        step_sessions: stepSessions,
                    },
                    variant_results: [
                        {
                            key: 'test',
                            sum: 95,
                            sum_squares: 95,
                            step_counts: [95, 48],
                            step_sessions: stepSessions,
                        },
                    ],
                    clickhouse_sql: longSql,
                    hogql: longSql,
                },
            ],
            secondaryMetricsResults: [],
        })

        const data = result.metrics.primary.results[0]?.data as Record<string, unknown>
        expect(data.clickhouse_sql).toBeUndefined()
        expect(data.hogql).toBeUndefined()
        const baseline = data.baseline as Record<string, unknown>
        expect(baseline.step_sessions).toBeUndefined()
        // Statistical fields must survive — they're what an MCP caller actually needs.
        expect(baseline.sum).toBe(100)
        expect(baseline.step_counts).toEqual([100, 50])
        const variants = data.variant_results as Array<Record<string, unknown>>
        expect(variants[0]?.step_sessions).toBeUndefined()
        expect(variants[0]?.sum).toBe(95)
    })

    it('strips the legacy `insight` visualization payload from each row', () => {
        // `insight` is a rendered visualization payload (list[dict[str, Any]]) used by
        // legacy trends/funnels charts
        const experiment = makeExperiment({
            metrics: [{ uuid: 'p-1', name: 'Primary', metric_type: 'mean' }],
            primary_metrics_ordered_uuids: ['p-1'],
        })

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: buildMetricEntries(experiment, 'primary'),
            secondaryMetricEntries: [],
            primaryMetricsResults: [
                {
                    baseline: { key: 'control', sum: 100, sum_squares: 100 },
                    insight: [{ breakdown_value: 'control', data: [1, 2, 3] }],
                },
            ],
            secondaryMetricsResults: [],
        })

        const data = result.metrics.primary.results[0]?.data as Record<string, unknown>
        expect(data.insight).toBeUndefined()
        expect((data.baseline as Record<string, unknown>).sum).toBe(100)
    })

    it('strips step_sessions from inside breakdown_results entries while preserving per-breakdown stats', () => {
        // breakdown_results carries stats that we keep. But each entry's
        // baseline/variants embed their own step_sessions which we strip.
        const experiment = makeExperiment({
            metrics: [{ uuid: 'p-1', name: 'Primary', metric_type: 'funnel' }],
            primary_metrics_ordered_uuids: ['p-1'],
        })
        const stepSessions = [Array.from({ length: 50 }, (_, i) => ({ event_uuid: `e-${i}` }))]

        const result = transformExperimentResults({
            experiment,
            exposures: baseExposures,
            primaryMetricEntries: buildMetricEntries(experiment, 'primary'),
            secondaryMetricEntries: [],
            primaryMetricsResults: [
                {
                    baseline: { key: 'control', sum: 100, sum_squares: 100 },
                    variant_results: [{ key: 'test', sum: 95, sum_squares: 95 }],
                    breakdown_results: [
                        {
                            breakdown_value: ['MacOS'],
                            baseline: {
                                key: 'control',
                                sum: 60,
                                sum_squares: 60,
                                step_counts: [60, 30],
                                step_sessions: stepSessions,
                            },
                            variants: [
                                {
                                    key: 'test',
                                    sum: 55,
                                    sum_squares: 55,
                                    step_counts: [55, 27],
                                    step_sessions: stepSessions,
                                },
                            ],
                        },
                    ],
                },
            ],
            secondaryMetricsResults: [],
        })

        const data = result.metrics.primary.results[0]?.data as Record<string, unknown>
        const breakdowns = data.breakdown_results as Array<Record<string, unknown>>
        expect(breakdowns).toHaveLength(1)
        expect(breakdowns[0]?.breakdown_value).toEqual(['MacOS'])

        const bdBaseline = breakdowns[0]?.baseline as Record<string, unknown>
        expect(bdBaseline.step_sessions).toBeUndefined()
        // Per-breakdown stats must survive — they're the whole point of breakdown_results.
        expect(bdBaseline.sum).toBe(60)
        expect(bdBaseline.step_counts).toEqual([60, 30])

        const bdVariants = breakdowns[0]?.variants as Array<Record<string, unknown>>
        expect(bdVariants[0]?.step_sessions).toBeUndefined()
        expect(bdVariants[0]?.sum).toBe(55)
        expect(bdVariants[0]?.step_counts).toEqual([55, 27])
    })
})

describe('exposure_criteria parsing — action-based exposure', () => {
    // Regression: experiment-results-get threw a ZodError ("expected
    // ExperimentEventExposureConfig") whenever the experiment's exposure was gated
    // on an action (kind 'ActionsNode') instead of a custom event, because the
    // shared exposure schema only modeled the event variant. The experiment GET and
    // the ExperimentExposureQuery built from it (client.ts) both run through this
    // schema, so a narrow union broke results for every action-exposure experiment.
    const actionExposureCriteria = {
        filterTestAccounts: true,
        exposure_config: { kind: 'ActionsNode' as const, id: 3, properties: [] },
    }

    it('parses an experiment whose exposure_config is an ActionsNode and preserves kind + id', () => {
        const experiment = makeExperiment({ exposure_criteria: actionExposureCriteria })
        expect(experiment.exposure_criteria?.exposure_config).toEqual({
            kind: 'ActionsNode',
            id: 3,
            properties: [],
        })
    })

    it('still parses the event-based exposure_config variant', () => {
        const experiment = makeExperiment({
            exposure_criteria: {
                filterTestAccounts: true,
                exposure_config: {
                    kind: 'ExperimentEventExposureConfig' as const,
                    event: '$pageview',
                    properties: [],
                },
            },
        })
        expect(experiment.exposure_criteria?.exposure_config).toEqual({
            kind: 'ExperimentEventExposureConfig',
            event: '$pageview',
            properties: [],
        })
    })

    it('accepts an ExperimentExposureQuery carrying action-based exposure criteria (the client.ts throw site)', () => {
        // client.ts builds this query from experiment.exposure_criteria and parses it
        // before POSTing to /query/. This is the exact call that surfaced the bug.
        const parsed = ExperimentExposureQuerySchema.parse({
            kind: 'ExperimentExposureQuery',
            experiment_id: 9,
            experiment_name: 'New upload button',
            exposure_criteria: actionExposureCriteria,
            start_date: '2026-01-01T00:00:00Z',
        })
        expect(parsed.exposure_criteria?.exposure_config).toEqual({ kind: 'ActionsNode', id: 3, properties: [] })
    })
})
