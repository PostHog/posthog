import { thresholdColor } from './metricsThresholds'

const FALLBACK = 'data-color-1'

describe('thresholdColor', () => {
    it('returns fallback when value is null', () => {
        expect(thresholdColor(null, [{ value: 0, color: 'green' }], FALLBACK)).toBe(FALLBACK)
    })

    it('returns fallback when there are no thresholds', () => {
        expect(thresholdColor(5, undefined, FALLBACK)).toBe(FALLBACK)
        expect(thresholdColor(5, [], FALLBACK)).toBe(FALLBACK)
    })

    it('uses the base color below the first step', () => {
        const t = [{ value: 80, color: 'red' }]
        expect(thresholdColor(50, t, FALLBACK)).toBe('red')
    })

    it('picks the highest step the value meets or exceeds', () => {
        const t = [
            { value: 0, color: 'green' },
            { value: 70, color: 'warning' },
            { value: 90, color: 'danger' },
        ]
        expect(thresholdColor(10, t, FALLBACK)).toBe('green')
        expect(thresholdColor(70, t, FALLBACK)).toBe('warning')
        expect(thresholdColor(85, t, FALLBACK)).toBe('warning')
        expect(thresholdColor(95, t, FALLBACK)).toBe('danger')
    })

    it('does not depend on entry order', () => {
        const t = [
            { value: 90, color: 'danger' },
            { value: 0, color: 'green' },
            { value: 70, color: 'warning' },
        ]
        expect(thresholdColor(85, t, FALLBACK)).toBe('warning')
        expect(thresholdColor(10, t, FALLBACK)).toBe('green')
    })
})
