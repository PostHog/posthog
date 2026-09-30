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
    ])('names what is wrong with %s', (_name, text, error) => {
        expect(parseScoutStructuredOutputSchema(text)).toEqual({ schema: null, error })
    })

    it.each([
        ['a record schema', JSON.stringify(verdictSchema), verdictSchema],
        // The API refuses regex keywords and references to other documents. Reading those rules
        // here as well could only refuse a schema the API accepts, so the save carries them.
        [
            'a schema the API judges, such as one with a regex keyword',
            '{"type": "object", "properties": {"a": {"type": "string", "pattern": "^a+$"}}}',
            { type: 'object', properties: { a: { type: 'string', pattern: '^a+$' } } },
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
