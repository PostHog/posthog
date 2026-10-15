import { safeColorToken, thresholdColor, worseDirection } from './metricsThresholds'

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

describe('worseDirection', () => {
    it.each([
        [
            'alarm at the top step',
            [
                { value: 90, color: 'danger' },
                { value: 0, color: 'success' },
            ],
            'up',
        ],
        [
            'alarm at the base step',
            [
                { value: 2, color: 'success' },
                { value: 0, color: 'red' },
            ],
            'down',
        ],
        [
            'no alarm color',
            [
                { value: 0, color: 'green' },
                { value: 10, color: 'warning' },
            ],
            null,
        ],
        ['a single step', [{ value: 0, color: 'danger' }], null],
        ['no thresholds', undefined, null],
    ])('%s', (_, thresholds, expected) => {
        expect(worseDirection(thresholds)).toBe(expected)
    })
})

describe('safeColorToken', () => {
    it('passes a plain token through', () => {
        expect(safeColorToken('danger', 'data-color-1')).toBe('danger')
        expect(safeColorToken('data-color-3', 'data-color-1')).toBe('data-color-3')
    })

    it('falls back on a token with class-breaking characters', () => {
        expect(safeColorToken('x) fixed inset-0 z-50', 'data-color-1')).toBe('data-color-1')
        expect(safeColorToken('red blue', 'data-color-1')).toBe('data-color-1')
        expect(safeColorToken('text-(--x)', 'data-color-1')).toBe('data-color-1')
    })
})
