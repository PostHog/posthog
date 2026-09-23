import { getUnmergeDisabledReason } from './manageFingerprintsLogic'

describe('manageFingerprintsLogic', () => {
    it.each([
        [2, 1, false, false, null],
        [5, 3, false, false, null],
        [2, 1, false, true, 'Unmerging in progress'],
        [2, 1, true, false, 'Wait for fingerprints to finish loading'],
        [1, 1, false, false, 'This issue only has one fingerprint and cannot be unmerged'],
        [3, 0, false, false, 'Select at least one fingerprint to unmerge'],
        // Unmerging every fingerprint would leave the issue with nothing in it.
        [3, 3, false, false, 'Leave at least one fingerprint on this issue'],
    ])(
        'blocks unmerging %p fingerprints with %p selected (loading: %p, unmerging: %p) with %p',
        (fingerprintCount, selectedCount, loading, unmerging, expected) => {
            expect(getUnmergeDisabledReason(fingerprintCount, selectedCount, loading, unmerging)).toBe(expected)
        }
    )
})
