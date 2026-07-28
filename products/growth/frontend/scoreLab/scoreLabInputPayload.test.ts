import type { InputFieldsEnumApi } from '../generated/api.schemas'
import { buildInputPayload, hasValidInput, inputDisabledReason } from './scoreLabInputPayload'

const NAME: InputFieldsEnumApi = 'name'
const HEADCOUNT: InputFieldsEnumApi = 'headcount'

describe('buildInputPayload', () => {
    it.each([
        ['fields' as const, [NAME, HEADCOUNT], 'SELECT 1', { input_fields: [NAME, HEADCOUNT], input_query: null }],
        ['query' as const, [NAME], 'SELECT 1', { input_fields: [], input_query: 'SELECT 1' }],
    ])("mode %s only sends that mode's input", (mode, fields, query, expected) => {
        expect(buildInputPayload(mode, fields, query)).toEqual(expected)
    })
})

describe('hasValidInput', () => {
    it.each([
        ['fields' as const, [], '', false],
        ['fields' as const, ['name'], '', true],
        ['query' as const, ['name'], '', false],
        ['query' as const, ['name'], '   ', false],
        ['query' as const, [], 'SELECT 1', true],
    ])('mode %s with fields %j and query %j -> %s', (mode, fields, query, expected) => {
        expect(hasValidInput(mode, fields, query)).toBe(expected)
    })
})

describe('inputDisabledReason', () => {
    it('flags empty field selection in fields mode', () => {
        expect(inputDisabledReason('fields', [], '')).toBe('Select at least one payload field')
    })

    it('flags an empty query in query mode', () => {
        expect(inputDisabledReason('query', [], '   ')).toBe('Enter a HogQL query')
    })

    it('returns undefined once the active mode has valid input', () => {
        expect(inputDisabledReason('fields', ['name'], '')).toBeUndefined()
        expect(inputDisabledReason('query', [], 'SELECT 1')).toBeUndefined()
    })
})
