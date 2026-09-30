import { parseScoutStructuredOutputSchema, scoutStructuredOutputFieldNames } from './scoutStructuredOutput'

describe('scoutStructuredOutput', () => {
    const verdictSchema = {
        type: 'object',
        properties: { verdict: { enum: ['good', 'bad'] }, reason: { type: 'string' } },
        required: ['verdict'],
    }

    it.each([
        ['blank text', '   ', null],
        ['invalid JSON', '{"type":', 'This is not valid JSON.'],
        ['an empty object', '{}', 'The schema must be a JSON object with at least one key.'],
        ['an array', '[{"type": "object"}]', 'The schema must be a JSON object with at least one key.'],
        ['a non-object root', '{"type": "string"}', 'The schema must set "type": "object" at its root.'],
        // Both constructs the config API refuses. Catching them here keeps a save that cannot
        // succeed from being a round trip to the server.
        [
            'a remote reference',
            '{"type": "object", "properties": {"a": {"$ref": "https://example.com/s.json"}}}',
            'The schema can only reference itself, so "$ref" must start with #.',
        ],
        [
            'a regex keyword',
            '{"type": "object", "properties": {"a": {"type": "string", "pattern": "^a+$"}}}',
            `The schema can't use "pattern". Use enum, type, length, or numeric bounds instead.`,
        ],
    ])('names what is wrong with %s', (_name, text, error) => {
        expect(parseScoutStructuredOutputSchema(text)).toEqual({ schema: null, error })
    })

    it.each([
        ['a record schema', JSON.stringify(verdictSchema), verdictSchema],
        // `pattern` here is a field of the record, not a JSON Schema keyword, so rejecting it
        // would block a schema the API accepts.
        [
            'a record field named pattern',
            '{"type": "object", "properties": {"pattern": {"type": "string"}}}',
            { type: 'object', properties: { pattern: { type: 'string' } } },
        ],
        [
            'an example payload carrying a pattern key',
            '{"type": "object", "properties": {"a": {"type": "object", "examples": [{"pattern": "x"}]}}}',
            { type: 'object', properties: { a: { type: 'object', examples: [{ pattern: 'x' }] } } },
        ],
    ])('accepts %s', (_name, text, schema) => {
        expect(parseScoutStructuredOutputSchema(text)).toEqual({ schema, error: null })
    })

    it('rejects a schema over the size the API accepts', () => {
        const properties = Object.fromEntries(
            Array.from({ length: 900 }, (_value, index) => [`field_${index}`, { type: 'string' }])
        )
        const { schema, error } = parseScoutStructuredOutputSchema(JSON.stringify({ type: 'object', properties }))

        expect(schema).toBeNull()
        expect(error).toContain('20000 byte limit')
    })

    it.each([
        ['a schema with properties', verdictSchema, ['verdict', 'reason']],
        ['a schema without properties', { type: 'object' }, []],
        ['no schema', null, []],
    ])('reads the record fields from %s', (_name, schema, fieldNames) => {
        expect(scoutStructuredOutputFieldNames(schema)).toEqual(fieldNames)
    })
})
