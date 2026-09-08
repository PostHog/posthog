import { parseToolOutputRecord } from './toolOutput'

describe('parseToolOutputRecord', () => {
    it.each([
        ['object', { id: 7 }, {}, { id: 7 }],
        ['empty object', {}, {}, null],
        ['JSON with flag', '{"id":7}', { command: 'call --json dashboard-update {"id":7}' }, { id: 7 }],
        [
            'TOON without flag',
            'id: 7\nname: Growth',
            { command: 'call dashboard-update {"id":7}' },
            { id: 7, name: 'Growth' },
        ],
        ['JSON fallback', '{"id":7}', { command: 'call dashboard-update {"id":7}' }, { id: 7 }],
        [
            'TOON fallback after JSON flag',
            'id: 7\nname: Growth',
            { command: 'call --json dashboard-update' },
            { id: 7, name: 'Growth' },
        ],
    ])('parses %s', (_case, rawOutput, rawInput, expected) => {
        expect(parseToolOutputRecord(rawOutput, rawInput)).toEqual(expected)
    })

    it.each([undefined, null, '', '[]', '{}', 'not a structured response', 7, ['id']])(
        'returns null for %p',
        (rawOutput) => {
            expect(parseToolOutputRecord(rawOutput, {})).toBeNull()
        }
    )

    it('does not reinterpret JSON-looking malformed output as TOON', () => {
        expect(parseToolOutputRecord('{"id":', { command: 'call dashboard-update' })).toBeNull()
    })
})
