import { cadenceForDataFreshness, dataFreshnessForCadence, endpointSyncFrequencyBounds } from './endpointRefreshCadence'

describe('endpointRefreshCadence', () => {
    it('maps every accepted freshness to a cadence and back', () => {
        for (const seconds of [900, 1800, 3600, 21600, 43200, 86400, 604800]) {
            const cadence = cadenceForDataFreshness(seconds)
            expect(cadence).not.toBeNull()
            expect(dataFreshnessForCadence(cadence!)).toBe(seconds)
        }
        expect(cadenceForDataFreshness(1234)).toBeNull()
        expect(dataFreshnessForCadence('30day')).toBeNull()
    })

    it.each([
        ['no plan floor', null, [], null],
        ['a floor on a bucket', 3600, ['15min', '30min'], '1 hour'],
        ['a floor between buckets', 4000, ['15min', '30min', '1hour'], '6 hours'],
    ])('with %s blocks only the cadences faster than the plan allows', (_, floor, blocked, planFloorLabel) => {
        const bounds = endpointSyncFrequencyBounds(floor)

        expect(bounds.options.filter((option) => !option.allowed).map((option) => option.cadence)).toEqual(blocked)
        expect(bounds.options.filter((option) => !option.allowed).every((option) => option.blocked_by === 'plan')).toBe(
            true
        )
        expect(bounds.options.map((option) => option.cadence)).not.toContain('30day')
        expect(bounds.plan_floor?.label ?? null).toBe(planFloorLabel)
    })
})
