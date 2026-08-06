/**
 * Runtime regression test for the metric null-injection bug.
 *
 * The generated zod for `metrics` is one flattened object holding every
 * metric-type field, each carrying `.default(null)`. In tool mode the server
 * runs `schema.safeParse(args)`, so zod fills every omitted field with `null`.
 * A clean mean metric then arrives at the API with `series`, `numerator`,
 * `denominator`, `completion_event`, `retention_window_*`, … all set to null,
 * and the backend (pydantic `extra="forbid"`) rejects them as `extra_forbidden`.
 *
 * These tests parse a minimal, valid metric and assert the parser does NOT
 * invent fields the caller never sent.
 */
import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/experiments'
import type { ToolBase, ZodObjectAny } from '@/tools/types'

function updateSchema(): z.ZodTypeAny {
    const factory = GENERATED_TOOLS['experiment-update'] as () => ToolBase<ZodObjectAny>
    return factory().schema as z.ZodTypeAny
}

/** Keys present-and-null in `parsed` that were absent from `sent` — i.e. invented by zod. */
function injectedNullKeys(sent: Record<string, unknown>, parsed: Record<string, unknown>): string[] {
    return Object.entries(parsed)
        .filter(([k, v]) => v === null && !(k in sent))
        .map(([k]) => k)
        .sort()
}

const CLEAN_METRICS: Array<[string, Record<string, unknown>]> = [
    [
        'mean',
        {
            kind: 'ExperimentMetric',
            metric_type: 'mean',
            name: 'clean mean',
            source: { kind: 'EventsNode', event: '$pageview', math: 'total' },
        },
    ],
    [
        'funnel',
        {
            kind: 'ExperimentMetric',
            metric_type: 'funnel',
            name: 'clean funnel',
            series: [{ kind: 'EventsNode', event: '$pageview' }],
        },
    ],
    [
        'ratio',
        {
            kind: 'ExperimentMetric',
            metric_type: 'ratio',
            name: 'clean ratio',
            numerator: { kind: 'EventsNode', event: '$pageview', math: 'total' },
            denominator: { kind: 'EventsNode', event: '$pageview', math: 'total' },
        },
    ],
    [
        'retention',
        {
            kind: 'ExperimentMetric',
            metric_type: 'retention',
            name: 'clean retention',
            start_event: { kind: 'EventsNode', event: '$pageview' },
            completion_event: { kind: 'EventsNode', event: '$pageview' },
            retention_window_start: 0,
            retention_window_end: 7,
            retention_window_unit: 'day',
            start_handling: 'first_seen',
        },
    ],
]

describe('experiment-update metric null injection', () => {
    it.each(CLEAN_METRICS)('does not inject foreign null fields into a %s metric', (_type, metric) => {
        const parsed = updateSchema().parse({ id: 123, metrics: [metric] }) as Record<string, unknown>
        const parsedMetric = (parsed.metrics as Record<string, unknown>[])[0]!
        expect(injectedNullKeys(metric, parsedMetric)).toEqual([])
    })

    it('still preserves explicit nulls the caller sends', () => {
        // conversion_window is a valid mean field; an explicit null must survive.
        const metric = {
            kind: 'ExperimentMetric',
            metric_type: 'mean',
            name: 'explicit null',
            source: { kind: 'EventsNode', event: '$pageview', math: 'total' },
            conversion_window: null,
        }
        const parsed = updateSchema().parse({ id: 123, metrics: [metric] }) as Record<string, unknown>
        const parsedMetric = (parsed.metrics as Record<string, unknown>[])[0]!
        expect(parsedMetric).toHaveProperty('conversion_window', null)
    })
})
