import { describe, expect, it } from 'vitest'

import { toMcpInputSchema } from '@/hono/tool-catalog'
import { ReadDataSchemaSchema } from '@/schema/tool-inputs'

describe('read-data-schema input', () => {
    it.each([
        [
            'query fields sent at the top level',
            { kind: 'event_properties', event_name: 'purchase' },
            { query: { kind: 'event_properties', event_name: 'purchase' } },
        ],
        [
            'a top-level events query',
            { kind: 'events', limit: 50 },
            { query: { kind: 'events', limit: 50, offset: 0 } },
        ],
        [
            'a top-level query alongside a natural-language description',
            { kind: 'events', query: 'which events exist?' },
            { query: { kind: 'events', limit: 500, offset: 0 } },
        ],
        [
            'the person_properties alias',
            { query: { kind: 'person_properties' } },
            { query: { kind: 'entity_properties', entity: 'person' } },
        ],
        [
            'the session_properties alias',
            { query: { kind: 'session_properties' } },
            { query: { kind: 'entity_properties', entity: 'session' } },
        ],
    ])('accepts %s', (_name, input, expected) => {
        expect(ReadDataSchemaSchema.parse(input)).toEqual(expected)
    })

    it('keeps a well-formed query even when a stray kind sits at the top level', () => {
        const parsed = ReadDataSchemaSchema.parse({
            kind: 'events',
            query: { kind: 'event_properties', event_name: 'purchase' },
        })

        expect(parsed).toEqual({ query: { kind: 'event_properties', event_name: 'purchase' } })
    })

    it('still rejects a call that names no kind', () => {
        expect(ReadDataSchemaSchema.safeParse({ event_name: 'purchase' }).success).toBe(false)
    })

    it('advertises the wrapped query as the only input shape', () => {
        const schema = toMcpInputSchema(ReadDataSchemaSchema) as Record<string, unknown>

        expect(schema['required']).toEqual(['query'])
        expect(Object.keys(schema['properties'] as Record<string, unknown>)).toEqual(['query'])
    })
})
