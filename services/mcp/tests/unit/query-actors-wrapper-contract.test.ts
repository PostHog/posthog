import { describe, expect, it } from 'vitest'

import { formatInputValidationError, rewrapFlattenedArguments } from '@/tools/exec'
import { GENERATED_TOOLS } from '@/tools/generated/query-wrappers'

const series = [{ kind: 'EventsNode', event: '$pageview' }]

/** A minimal source query per actors tool, with the selectors that tool requires beside it. */
const actorsCalls = [
    ['query-trends-actors', { series }, {}],
    ['query-lifecycle-actors', { series }, { day: '2024-01-15', status: 'new' }],
    ['query-stickiness-actors', { series }, { day: 3 }],
    ['query-funnel-actors', { series: [...series, { kind: 'EventsNode', event: 'user signed up' }] }, {}],
    ['query-paths-actors', { pathsFilter: {} }, {}],
    [
        'query-retention-actors',
        {
            retentionFilter: {
                targetEntity: { type: 'events', id: '$pageview' },
                returningEntity: { type: 'events', id: '$pageview' },
            },
        },
        {},
    ],
] as const

describe('tools whose payload sits under a required `source` query', () => {
    it.each(actorsCalls)('%s accepts the source query nested with its selectors', (name, source, selectors) => {
        const parsed = GENERATED_TOOLS[name]!().schema.safeParse({ source, ...selectors })

        expect(parsed.error?.issues ?? []).toEqual([])
    })

    it.each(actorsCalls)('%s names the nesting mistake when the source query is sent flattened', (name, source) => {
        const tool = GENERATED_TOOLS[name]!()
        const rejected = tool.schema.safeParse(source, { reportInput: true })
        expect(rejected.success).toBe(false)

        const message = formatInputValidationError(name, rejected.error!, source, tool.schema)

        expect(message).toContain('missing required parameter: source')
        expect(message).toContain('the fields you sent belong inside it')
        expect(message).toContain('resend them as {"source": {')
    })

    it.each(actorsCalls.filter(([, , selectors]) => Object.keys(selectors).length === 0))(
        '%s rewraps a flattened source query back into the call the caller meant',
        (name, source) => {
            const tool = GENERATED_TOOLS[name]!()
            const rejected = tool.schema.safeParse(source, { reportInput: true })

            expect(rewrapFlattenedArguments(rejected.error!, source, tool.schema)).toEqual({ source })
        }
    )

    it('rewraps a flattened trends query whose series array collides with the selector index', () => {
        const tool = GENERATED_TOOLS['query-trends-actors']!()
        const flattened = { dateRange: { date_from: '-7d' }, interval: 'day', series }
        const rejected = tool.schema.safeParse(flattened, { reportInput: true })

        expect(rewrapFlattenedArguments(rejected.error!, flattened, tool.schema)).toEqual({ source: flattened })
    })

    it('keeps a series index the caller meant as a selector beside the source', () => {
        const tool = GENERATED_TOOLS['query-trends-actors']!()
        const flattened = { series: 1, dateRange: { date_from: '-7d' } }
        const rejected = tool.schema.safeParse(flattened, { reportInput: true })

        const message = formatInputValidationError('query-trends-actors', rejected.error!, flattened, tool.schema)

        expect(message).toContain('resend them as {"source": {"dateRange": ...}, "series": ...}')
    })

    it('accepts a total-value trends source, which has no day to select', () => {
        const parsed = GENERATED_TOOLS['query-trends-actors']!().schema.safeParse({
            source: { series, trendsFilter: { display: 'BoldNumber' } },
        })

        expect(parsed.error?.issues ?? []).toEqual([])
    })
})
