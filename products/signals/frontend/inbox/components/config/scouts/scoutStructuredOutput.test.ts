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
        [
            'nesting that parses but is too deep to serialize',
            `{"type": "object", "default": ${'['.repeat(100000)}${']'.repeat(100000)}}`,
            'The schema is nested too deeply. Use fewer nested levels.',
        ],
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

    const stringFields = (count: number): Record<string, unknown> => ({
        type: 'object',
        properties: Object.fromEntries(
            Array.from({ length: count }, (_value, index) => [`field_${index}`, { type: 'string' }])
        ),
    })

    // Each pair sits on the API's limit: the byte counts are what Python's json.dumps gives, and
    // compact UTF-8 counts both schemas in a pair well under the limit.
    it.each([
        ['608 fields, 19988 bytes to the API', stringFields(608), false],
        ['609 fields, 20021 bytes to the API', stringFields(609), true],
        ['3327 accented letters, 19999 bytes to the API', { type: 'object', description: 'é'.repeat(3327) }, false],
        ['3328 accented letters, 20005 bytes to the API', { type: 'object', description: 'é'.repeat(3328) }, true],
    ])('measures the size the way the API does, for %s', (_name, input, refused) => {
        const { schema, error } = parseScoutStructuredOutputSchema(JSON.stringify(input))

        expect(schema).toEqual(refused ? null : input)
        expect(error).toEqual(refused ? 'The schema is over the 20000 byte limit. Describe fewer fields.' : null)
    })

    it.each([
        ['a schema with properties', verdictSchema, ['verdict', 'reason']],
        ['a schema without properties', { type: 'object' }, []],
        ['no schema', null, []],
    ])('reads the record fields from %s', (_name, schema, fieldNames) => {
        expect(scoutStructuredOutputFieldNames(schema)).toEqual(fieldNames)
    })
})
