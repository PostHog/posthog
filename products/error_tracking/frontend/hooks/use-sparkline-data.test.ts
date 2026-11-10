import { ErrorTrackingSpikeEvent } from 'lib/components/Errors/types'

import { applyVolumeSpikeHighlights } from './use-sparkline-data'

const HOUR_MS = 60 * 60 * 1000
const BASE = Date.parse('2024-01-01T00:00:00.000Z')

function spikeAt(offsetMs: number, currentBucketValue: number, computedBaseline: number): ErrorTrackingSpikeEvent {
    return {
        id: `spike-${offsetMs}-${currentBucketValue}`,
        issue: { id: 'issue', name: null, description: null },
        detected_at: new Date(BASE + offsetMs).toISOString(),
        current_bucket_value: currentBucketValue,
        computed_baseline: computedBaseline,
    }
}

describe('applyVolumeSpikeHighlights', () => {
    const data = [0, 1, 2].map((index) => ({ date: new Date(BASE + index * HOUR_MS), value: 10 }))

    it.each([
        {
            name: 'the largest multiplier in the bucket',
            spikes: [spikeAt(HOUR_MS, 30, 10), spikeAt(HOUR_MS + 60_000, 50, 10)],
            expected: 5,
        },
        { name: 'no multiplier for a zero baseline', spikes: [spikeAt(HOUR_MS, 30, 0)], expected: undefined },
    ])('flags the bucket with $name', ({ spikes, expected }) => {
        const [before, spiked, after] = applyVolumeSpikeHighlights(data, spikes)

        expect(spiked).toMatchObject({ isSpike: true, spikeMultiplier: expected })
        expect(before.isSpike).toBeUndefined()
        expect(after.isSpike).toBeUndefined()
    })

    it('flags every bucket that has a spike when spikes arrive out of time order', () => {
        const [first, second, third] = applyVolumeSpikeHighlights(data, [
            spikeAt(2 * HOUR_MS, 20, 10),
            spikeAt(0, 30, 10),
        ])

        expect(first).toMatchObject({ isSpike: true, spikeMultiplier: 3 })
        expect(second.isSpike).toBeUndefined()
        expect(third).toMatchObject({ isSpike: true, spikeMultiplier: 2 })
    })
})
