// Throwaway fixture validating the jest quarantine adapter end to end in CI. Never merge.
describe('QuarantineProduct', () => {
    test('always fails', () => {
        expect('e2e deliberate product-scope failure').toBe('tolerated')
    })
})
