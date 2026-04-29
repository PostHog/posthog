import { getNarrowDateRange } from './errorTrackingIssueSceneLogic'

describe('getNarrowDateRange', () => {
    it('returns a one-hour-each-side window for a valid ISO timestamp', () => {
        const range = getNarrowDateRange('2026-04-26T19:08:05.280Z')
        expect(range).toEqual({
            date_from: '2026-04-26T18:08:05.280Z',
            date_to: '2026-04-26T20:08:05.280Z',
        })
    })

    it('returns null for an Invalid Date (e.g. timestamp where + offset got URL-decoded as space)', () => {
        // Reproduces the production bug: the URL `?timestamp=2026-04-26T19:08:05.280000+01:00`
        // round-trips through router params with the `+` decoded back as a space.
        const malformed = '2026-04-26T19:08:05.280000 01:00'
        expect(getNarrowDateRange(malformed)).toBeNull()
    })

    it('returns null for an empty string', () => {
        expect(getNarrowDateRange('')).toBeNull()
    })

    it('returns null for a clearly bogus value', () => {
        expect(getNarrowDateRange('not-a-date')).toBeNull()
    })
})
