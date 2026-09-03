import {
    AIEnrichmentOutputField,
    buildOutputFieldsPayload,
    hasValidOutputFields,
    outputFieldsDisabledReason,
} from './aiEnrichmentOutputFields'

const field = (key: string): AIEnrichmentOutputField => ({ key, type: 'boolean', description: '' })

describe('aiEnrichmentOutputFields', () => {
    it('drops half-typed rows from the payload, which the API rejects as an invalid key', () => {
        expect(buildOutputFieldsPayload([field('is_ai'), field(''), field('   ')])).toEqual([field('is_ai')])
    })

    it.each([
        [[], false],
        [[field('')], false],
        [[field('  ')], false],
        [[field(''), field('is_ai')], true],
    ])('%j has usable output fields: %s', (fields, expected) => {
        expect(hasValidOutputFields(fields)).toBe(expected)
    })

    it('gives a reason only while nothing usable is entered', () => {
        expect(outputFieldsDisabledReason([field('')])).toBe('Add at least one output field')
        expect(outputFieldsDisabledReason([field('is_ai')])).toBeUndefined()
    })
})
