import { formatMetricValue, unitAxisFormatter } from './metricsUnits'

describe('formatMetricValue', () => {
    it.each([
        // no unit
        [1234, undefined, '1.23K'],
        [0, undefined, '0'],
        // bytes (binary)
        [0, 'By', '0 B'],
        [512, 'By', '512 B'],
        [1024, 'By', '1 KiB'],
        [1536, 'By', '1.5 KiB'],
        [1024 ** 2, 'By', '1 MiB'],
        [2.5 * 1024 ** 3, 'By', '2.5 GiB'],
        // binary-prefixed UCUM
        [2, 'KiBy', '2 KiB'],
        [3, 'MiBy', '3 MiB'],
        // seconds
        [2.5, 's', '2.5 s'],
        [0.34, 's', '340 ms'],
        [0.0005, 's', '500 µs'],
        [0.0000002, 's', '200 ns'],
        [340, 'ms', '340 ms'],
        [1500, 'ms', '1.5 s'],
        [250000, 'us', '250 ms'],
        // percent
        [42.5, '%', '42.5%'],
        // ratio (UCUM "1")
        [0.12, '1', '12%'],
        [1, '1', '100%'],
        [12, '1', '12'],
        // rates
        [88, '1/s', '88/s'],
        [88, '{request}/s', '88 request/s'],
        [1500, '{message}/s', '1.5K message/s'],
        // unknown unit falls back to compact + suffix
        [1234, 'widgets', '1.23K widgets'],
    ])('formats %s with unit %s as %s', (value, unit, expected) => {
        expect(formatMetricValue(value, unit)).toBe(expected)
    })

    it('handles negative values', () => {
        expect(formatMetricValue(-1024, 'By')).toBe('-1 KiB')
        expect(formatMetricValue(-0.5, '1')).toBe('-50%')
    })
})

describe('unitAxisFormatter', () => {
    it('binds the unit into a reusable formatter', () => {
        const fmt = unitAxisFormatter('ms')
        expect(fmt(340)).toBe('340 ms')
        expect(fmt(2000)).toBe('2 s')
    })

    it('falls back to compact with no unit', () => {
        expect(unitAxisFormatter(undefined)(1500)).toBe('1.5K')
    })
})
