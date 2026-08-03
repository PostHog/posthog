import { shouldFireAutoSeek } from './ReplayObservation'

describe('shouldFireAutoSeek', () => {
    const base = { trigger: 1, seekedForTrigger: null, startMs: 100, endMs: 200, snapshotsLoaded: true }

    it.each([
        { description: 'metadata and snapshots are both ready', overrides: {}, expected: true },
        {
            description: 'metadata has landed but the snapshot source list has not',
            overrides: { snapshotsLoaded: false },
            expected: false,
        },
        { description: 'metadata has not landed yet', overrides: { startMs: null, endMs: null }, expected: false },
        {
            description: 'this trigger has already fired a seek',
            overrides: { seekedForTrigger: 1 },
            expected: false,
        },
        {
            description: 'a new trigger arrives after a previous one already seeked',
            overrides: { seekedForTrigger: 0 },
            expected: true,
        },
    ])('$description', ({ overrides, expected }) => {
        expect(shouldFireAutoSeek({ ...base, ...overrides })).toBe(expected)
    })
})
