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
        ['no input at all', {}, { query: { kind: 'events', limit: 500, offset: 0 } }],
        ['an empty query object', { query: {} }, { query: { kind: 'events', limit: 500, offset: 0 } }],
        [
            'a free-text query with nothing else to go on',
            { query: 'what data do we collect?' },
            { query: { kind: 'events', limit: 500, offset: 0 } },
        ],
        ['a kind named as a bare string', { query: 'events' }, { query: { kind: 'events', limit: 500, offset: 0 } }],
        [
            'a kind alias named as a bare string',
            { query: 'person_properties' },
            { query: { kind: 'entity_properties', entity: 'person' } },
        ],
        [
            'the event_names kind alias',
            { query: { kind: 'event_names' } },
            { query: { kind: 'events', limit: 500, offset: 0 } },
        ],
        [
            'the person_property_values alias',
            { query: { kind: 'person_property_values', property_name: 'email' } },
            { query: { kind: 'entity_property_values', entity: 'person', property_name: 'email' } },
        ],
        [
            'the event field alias',
            { kind: 'event_properties', event: 'purchase' },
            { query: { kind: 'event_properties', event_name: 'purchase' } },
        ],
        [
            'a one-event list',
            { query: { kind: 'event_properties', event_names: ['purchase'] } },
            { query: { kind: 'event_properties', event_name: 'purchase' } },
        ],
        [
            'the group_type field alias',
            { query: { kind: 'entity_properties', group_type: 'organization' } },
            { query: { kind: 'entity_properties', entity: 'organization' } },
        ],
        [
            'an action id written as a string',
            { query: { kind: 'action_properties', action_id: '42' } },
            { query: { kind: 'action_properties', action_id: 42 } },
        ],
        [
            'a page size written as a string',
            { query: { kind: 'events', limit: '50' } },
            { query: { kind: 'events', limit: 50, offset: 0 } },
        ],
        [
            'a page size above the maximum',
            { query: { kind: 'events', limit: 1000 } },
            { query: { kind: 'events', limit: 500, offset: 0 } },
        ],
        [
            'a missing kind inferred from the fields',
            { event_name: 'purchase', property_name: 'plan' },
            { query: { kind: 'event_property_values', event_name: 'purchase', property_name: 'plan' } },
        ],
        [
            'an ambiguous kind resolved by the fields',
            { query: { kind: 'properties', entity: 'person' } },
            { query: { kind: 'entity_properties', entity: 'person' } },
        ],
        [
            'paging sent alongside a single-entity read',
            { query: { kind: 'event_properties', event_name: 'purchase', limit: 50 } },
            { query: { kind: 'event_properties', event_name: 'purchase' } },
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

    it.each([
        ['a search term the events read cannot honor', { kind: 'events', search: 'purchase' }],
        [
            'a property name the event_properties read ignores',
            { kind: 'event_properties', event_name: 'a', property_name: 'b' },
        ],
        ['a subject this tool does not read', { table: 'stripe_invoices' }],
        ['a multi-event list no single read can answer', { kind: 'event_properties', event_names: ['a', 'b'] }],
    ])('still rejects %s', (_name, input) => {
        expect(ReadDataSchemaSchema.safeParse(input).success).toBe(false)
    })

    it('advertises the wrapped query as the only input shape', () => {
        const schema = toMcpInputSchema(ReadDataSchemaSchema) as Record<string, unknown>

        expect(schema['required']).toEqual(['query'])
        expect(Object.keys(schema['properties'] as Record<string, unknown>)).toEqual(['query'])
    })
})
