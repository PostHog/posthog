import { learningBaselineLabel } from './LogsAnomalies'

const WINDOW_END = '2026-08-06T00:00:00Z'

describe('LogsAnomalies', () => {
    describe('learningBaselineLabel', () => {
        // A truncating diff read a 2.9 day wait as "2 more days", which promises the
        // band a day early. A partial day still needs a whole day of data.
        it.each([
            [null, 'No expected range for this window'],
            ['2026-08-08T21:36:00Z', 'Learning baseline · 3 more days of history'],
            ['2026-08-07T04:48:00Z', 'Learning baseline · 2 more days of history'],
            ['2026-08-07T00:00:00Z', 'Learning baseline · 1 more day of history'],
            ['2026-08-20T00:00:00Z', 'Learning baseline · 14 more days of history'],
        ])('formats readiness %s as %s', (bandReadyAt, expected) => {
            expect(learningBaselineLabel(bandReadyAt, WINDOW_END)).toBe(expected)
        })

        // The band can land between the fetch and the render. The tag still has to read
        // as a wait, never as "0 more days".
        it.each([WINDOW_END, '2026-08-05T00:00:00Z'])('floors a lapsed wait at one day (%s)', (bandReadyAt) => {
            expect(learningBaselineLabel(bandReadyAt, WINDOW_END)).toBe('Learning baseline · 1 more day of history')
        })
    })
})
