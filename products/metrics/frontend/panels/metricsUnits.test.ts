import { formatMetricValue, metricValuesFormatter } from './metricsUnits'

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
        // a zero tick on a duration axis reads in seconds, not the smallest unit
        [0, 'ms', '0 s'],
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
        [2048, 'By/s', '2 KiB/s'],
        // unknown unit falls back to compact + suffix
        [1234, 'widgets', '1.23K widgets'],
        // small nonzero values keep two significant digits instead of rounding to zero
        [0.0012, undefined, '0.0012'],
        [0.0042, '%', '0.0042%'],
        [0.00005, '1', '0.005%'],
        [0.004, '1/s', '0.004/s'],
        [0.0031, '{request}/s', '0.0031 request/s'],
    ])('formats %s with unit %s as %s', (value, unit, expected) => {
        expect(formatMetricValue(value, unit)).toBe(expected)
    })

    it('handles negative values', () => {
        expect(formatMetricValue(-1024, 'By')).toBe('-1 KiB')
        expect(formatMetricValue(-0.5, '1')).toBe('-50%')
    })
})

describe('metricValuesFormatter', () => {
    it.each([
        // a ratio picks one scale for every value shown together, from the largest of them
        ['1', [0, 0.5, 1, 1.5, 2], ['0', '0.5', '1', '1.5', '2']],
        ['1', [-2, 0.5], ['-2', '0.5']],
        ['1', [0, 0.25, 1], ['0%', '25%', '100%']],
        // other units still format each value on its own
        ['ms', [340, 2000], ['340 ms', '2 s']],
        [undefined, [1500], ['1.5K']],
    ])('formats unit %s over values %j', (unit, values, expected) => {
        const fmt = metricValuesFormatter(unit, values)
        expect(values.map(fmt)).toEqual(expected)
    })
})
