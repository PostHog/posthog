import { ChangeRequest } from '~/types'

import { isChangeRequestForCurrentRun } from 'products/experiments/frontend/experimentActions'

const RUN = { start_date: '2026-10-28T13:00:00.123456Z', end_date: null }

describe('isChangeRequestForCurrentRun', () => {
    test.each([
        ['a request with no run dates', {}, RUN, true],
        [
            'the same run written with another offset',
            { run_started_at: '2026-10-28T13:00:00.123456+00:00', run_ended_at: null },
            RUN,
            true,
        ],
        [
            'a run that was reset and relaunched',
            { run_started_at: '2026-10-01T09:00:00+00:00', run_ended_at: null },
            RUN,
            false,
        ],
        [
            'a run that has ended since',
            { run_started_at: '2026-10-28T13:00:00.123456+00:00', run_ended_at: null },
            { ...RUN, end_date: '2026-10-29T08:00:00Z' },
            false,
        ],
    ])('%s', (_name, intent, experiment, expected) => {
        expect(isChangeRequestForCurrentRun({ intent } as ChangeRequest, experiment)).toBe(expected)
    })
})
