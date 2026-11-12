import { triageLabel } from './InboxTriageButton'

describe('triageLabel', () => {
    test.each([
        [1, false, false, 'Triage 1 report'],
        [1000, true, false, 'Triage 1,000+ reports'],
        [1000, true, true, 'Triage 1,000+'],
        [1, true, false, 'Triage 1+ reports'],
    ])('labels a count of %s (capped: %s, compact: %s) as %s', (count, countIsCapped, compact, expected) => {
        expect(triageLabel(count, countIsCapped, compact)).toEqual(expected)
    })
})
