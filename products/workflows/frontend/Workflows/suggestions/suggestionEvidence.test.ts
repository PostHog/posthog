import { evidenceDisagrees, formatValue, readUnit } from './suggestionEvidence'

describe('suggestionEvidence', () => {
    it.each([
        ['a rate', 0.0865, 'rate' as const, '8.6%'],
        ['a rate of zero', 0, 'rate' as const, '0.0%'],
        ['a rate of one', 1, 'rate' as const, '100.0%'],
        ['a count of one', 1, 'count' as const, '1'],
        ['a count', 240, 'count' as const, '240'],
        ['no unit', 0.0865, null, '0.0865'],
    ])('formats %s', (_name, value, unit, expected) => {
        expect(formatValue(value, unit)).toBe(expected)
    })

    it('has nothing to show for a value that is not a number', () => {
        expect(formatValue(null, 'rate')).toBeNull()
        expect(formatValue('8.65%', 'rate')).toBeNull()
    })

    it.each([
        ['rate', 'rate'],
        ['count', 'count'],
        ['percent', null],
        [undefined, null],
    ])('reads the unit %s', (raw, expected) => {
        expect(readUnit(raw)).toBe(expected)
    })

    const measured = {
        version: 1,
        window: '-7d',
        target: { metric: 'email open rate', value: 0.076, n: 132, below_minimum_sample: false },
        click_through: { metric: 'click rate', value: 0.008, n: 132, below_minimum_sample: false },
        guardrails: [],
    }

    it.each([
        ['the same number', { unit: 'rate', current_value: 0.0758, n: 132 }, false],
        ['a number a whole point off', { unit: 'rate', current_value: 0.09, n: 132 }, true],
        ['a different denominator', { unit: 'rate', current_value: 0.076, n: 500 }, true],
        ['a count, which is not compared', { unit: 'count', current_value: 10, n: 132 }, false],
    ])('flags %s against what PostHog measured', (_name, evidence, expected) => {
        expect(evidenceDisagrees(evidence, measured)).toBe(expected)
    })
})
