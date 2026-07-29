import { computeProgressFraction, selectProgressTarget } from './progress'

describe('progress', () => {
    describe('selectProgressTarget', () => {
        it.each([
            ['no goal lines', undefined, null],
            ['an empty list', [], null],
            // "Add goal line" seeds a zero value, so an untouched goal line must not become the target
            ['only a zero-value goal line', [{ label: 'Q4 Goal', value: 0 }], null],
            ['only a negative goal line', [{ label: 'Limit', value: -10 }], null],
            [
                'the first usable goal line',
                [
                    { label: 'Untouched', value: 0 },
                    { label: 'Q4 plan', value: 500, borderColor: '#ff0000' },
                    { label: 'Stretch', value: 900 },
                ],
                { label: 'Q4 plan', value: 500, color: '#ff0000' },
            ],
        ])('returns %s', (_name, goalLines, expected) => {
            expect(selectProgressTarget(goalLines)).toEqual(expected)
        })
    })

    describe('computeProgressFraction', () => {
        it.each([
            [50, 200, 0.25],
            [200, 200, 1],
            [300, 200, 1.5],
            [-50, 200, -0.25],
            [null, 200, 0],
            [undefined, 200, 0],
            [50, 0, 0],
        ])('maps %s against %s to %s', (value, target, expected) => {
            expect(computeProgressFraction(value, target)).toEqual(expected)
        })
    })
})
