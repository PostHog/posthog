import { suggestNextVersion } from './versionBump'

describe('suggestNextVersion', () => {
    it.each([
        ['ai-pilled-clay-v1', 'ai-pilled-clay-v2'],
        ['ai-pilled-clay-v9', 'ai-pilled-clay-v10'],
        ['ai-pilled-clay', 'ai-pilled-clay-v2'],
        ['lab-draft', 'lab-draft-v2'],
        ['', 'v1'],
        ['   ', 'v1'],
    ])('bumps %s to %s', (version, expected) => {
        expect(suggestNextVersion(version)).toBe(expected)
    })
})
