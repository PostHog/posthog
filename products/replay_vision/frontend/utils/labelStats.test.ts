import { dayjs } from 'lib/dayjs'

import { fillLabelDays } from './labelStats'

describe('fillLabelDays', () => {
    it('expands sparse day counts into a contiguous window with zero-filled gaps', () => {
        // Date-only string parses as local midnight, keeping day boundaries stable across timezones.
        const today = dayjs('2026-07-03')
        const result = fillLabelDays(
            [
                { date: '2026-07-01', up: 2, down: 1 },
                { date: '2026-07-03', up: 0, down: 3 },
                { date: '2026-05-01', up: 9, down: 9 }, // outside the window, dropped
            ],
            5,
            today
        )

        expect(result.labels).toEqual(['Jun 29', 'Jun 30', 'Jul 1', 'Jul 2', 'Jul 3'])
        // Version markers match bars on these, so they must be full dates, not year-less labels.
        expect(result.dates).toEqual(['2026-06-29', '2026-06-30', '2026-07-01', '2026-07-02', '2026-07-03'])
        expect(result.up).toEqual([0, 0, 2, 0, 0])
        expect(result.down).toEqual([0, 0, 1, 0, 3])
    })
})
