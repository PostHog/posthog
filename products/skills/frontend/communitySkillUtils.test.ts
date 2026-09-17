import { communityScoutCadenceLabel } from './communitySkillUtils'

describe('communityScoutCadenceLabel', () => {
    it.each([
        [90, 'Runs every 90 minutes'],
        [1439, 'Runs every 1439 minutes'],
        [2160, 'Runs every 36 hours'],
        [2880, 'Runs every 2 days'],
    ])('keeps the exact cadence for %i minutes', (run_interval_minutes, expected) => {
        expect(communityScoutCadenceLabel({ run_interval_minutes })).toBe(expected)
    })
})
