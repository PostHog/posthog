import { describe, expect, it } from 'vitest'
import type { z } from 'zod'

import { GENERATED_TOOLS } from '@/tools/generated/tracing'

describe('tracing GET tools — dateRange object-json-string cast', () => {
    it.each([
        ['apm-services-list', {}],
        ['apm-attributes-list', {}],
        ['apm-attribute-values-list', { key: 'http.method' }],
    ] as const)('%s accepts dateRange as an object or a JSON string', (toolName, extras) => {
        const schema = GENERATED_TOOLS[toolName]!().schema as z.ZodTypeAny

        const fromObject = schema.parse({ ...extras, dateRange: { date_from: '-1h' } }) as Record<string, unknown>
        const fromString = schema.parse({ ...extras, dateRange: '{"date_from":"-1h"}' }) as Record<string, unknown>

        expect(fromObject.dateRange).toBe('{"date_from":"-1h"}')
        expect(fromString.dateRange).toBe('{"date_from":"-1h"}')
    })
})
