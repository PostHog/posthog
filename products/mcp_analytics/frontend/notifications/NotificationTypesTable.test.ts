import { statusLabel } from './NotificationTypesTable'

describe('statusLabel', () => {
    it.each([
        [{ total: 0, enabled: 0, truncated: false }, 'Not set up'],
        [{ total: 1, enabled: 1, truncated: false }, 'On'],
        [{ total: 2, enabled: 2, truncated: false }, '2 on'],
        [{ total: 1, enabled: 0, truncated: false }, 'Paused'],
        [{ total: 3, enabled: 0, truncated: false }, '3 paused'],
        [{ total: 2, enabled: 1, truncated: false }, '1 of 2 on'],
        [{ total: 2, enabled: 1, truncated: true }, '1+ on'],
        [{ total: 2, enabled: 0, truncated: true }, '2+ paused'],
        [{ total: 0, enabled: 0, truncated: true }, 'Unknown'],
    ])('describes %j as %s', (counts, expected) => {
        expect(statusLabel(counts)).toBe(expected)
    })
})
