import { alertTagOptions } from './scannerAlertUtils'

describe('alertTagOptions', () => {
    it('keeps the configured categories first and in configuration order', () => {
        expect(alertTagOptions(['checkout', 'onboarding'], ['analytics'])).toEqual([
            { key: 'checkout', label: 'checkout' },
            { key: 'onboarding', label: 'onboarding' },
            { key: 'analytics', label: 'analytics', tooltip: 'Freeform tag seen in observations' },
        ])
    })

    it('does not repeat a configured category that observations also carried', () => {
        expect(alertTagOptions(['checkout', 'checkout'], ['checkout', 'rage'])).toEqual([
            { key: 'checkout', label: 'checkout' },
            { key: 'rage', label: 'rage', tooltip: 'Freeform tag seen in observations' },
        ])
    })

    it('returns nothing when the scanner has no tags at all', () => {
        expect(alertTagOptions([], [])).toEqual([])
    })
})
