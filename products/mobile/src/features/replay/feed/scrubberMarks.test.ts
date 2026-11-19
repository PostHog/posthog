import { clusterTicks, MARK_GAP, type ScrubberTick } from './scrubberMarks'

function tick(seconds: number, kind: ScrubberTick['kind'] = 'rage'): ScrubberTick {
    return { key: `${kind}-${seconds}`, seconds, kind, label: kind }
}

describe('scrubber marks', () => {
    test('a thousand events over a whole recording draw at most one mark per slot', () => {
        const ticks = Array.from({ length: 1000 }, (_unused, index) => tick((index * 1800) / 1000))
        const marks = clusterTicks(ticks, 0, 1800, 360)
        expect(marks.length).toBeLessThanOrEqual(360 / MARK_GAP)
        expect(marks.length).toBeGreaterThan(40)
    })

    test.each([
        [
            'an error beats a rage click in the same slot',
            [tick(10, 'rage'), tick(10.5, 'error')],
            0,
            1800,
            ['error-10.5'],
        ],
        ['the earlier of two marks of one kind wins', [tick(10.5), tick(10)], 0, 1800, ['rage-10']],
        ['marks outside the range are dropped', [tick(5, 'error'), tick(30), tick(70)], 20, 60, ['rage-30']],
    ])('%s', (_name, ticks, start, end, keys) => {
        expect(clusterTicks(ticks, start, end, 360).map((mark) => mark.key)).toEqual(keys)
    })
})
