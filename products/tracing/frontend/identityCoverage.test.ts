import { formatIdentityCoverage } from './identityCoverage'

describe('formatIdentityCoverage', () => {
    // A reading of 0% or 100% would say the count covers nothing, or all of it, when neither
    // is true.
    it.each([
        ['no covered spans', 0, 1000, '0%'],
        ['no spans at all', 0, 0, '0%'],
        ['a partly covered set', 400, 1000, '40%'],
        ['a sliver that would round to zero', 1, 1000, '<1%'],
        ['almost every span', 999, 1000, '>99%'],
        ['every span', 1000, 1000, '100%'],
    ])('reports %s', (_name, covered, total, expected) => {
        expect(formatIdentityCoverage(covered, total)).toBe(expected)
    })
})
