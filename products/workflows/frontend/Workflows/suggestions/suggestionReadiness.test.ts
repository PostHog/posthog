import { dayjs } from 'lib/dayjs'

import type { HogFlowOptimizationApi } from '../../generated/api.schemas'
import { suggestionReadiness } from './suggestionReadiness'

const NOW = dayjs('2026-11-20T15:00:00Z')

function optimization(overrides: {
    enabled?: boolean
    trackedSends?: number
    liveHoursAgo?: number
    lastCheckedHoursAgo?: number | null
    nextCheckInHours?: number | null
    noSample?: boolean
}): HogFlowOptimizationApi {
    const {
        enabled = true,
        trackedSends = 30,
        liveHoursAgo = 120,
        lastCheckedHoursAgo = 6,
        nextCheckInHours = 18,
        noSample = false,
    } = overrides
    return {
        enabled,
        scout_status: 'running',
        sample: noSample
            ? null
            : {
                  reached: trackedSends >= 20 && liveHoursAgo >= 48,
                  tracked_sends: trackedSends,
                  required_sends: 20,
                  version_live_since: NOW.subtract(liveHoursAgo, 'hour').toISOString(),
              },
        schedule: {
            last_checked_at:
                lastCheckedHoursAgo === null ? null : NOW.subtract(lastCheckedHoursAgo, 'hour').toISOString(),
            next_check_at: nextCheckInHours === null ? null : NOW.add(nextCheckInHours, 'hour').toISOString(),
        },
    }
}

describe('suggestionReadiness', () => {
    test.each([
        ['off, before any data', optimization({ enabled: false, trackedSends: 4 }), 'Turn on suggestions to start'],
        [
            'short on sends and too new',
            optimization({ trackedSends: 12, liveHoursAgo: 30 }),
            'Needs 8 more tracked sends',
        ],
        ['one send short', optimization({ trackedSends: 19 }), 'Needs 1 more tracked send'],
        [
            'enough sends on a version under two days old',
            optimization({ liveHoursAgo: 30 }),
            'Can be judged from tomorrow at 9:00 AM',
        ],
        ['ready, checked before', optimization({}), 'Next check around tomorrow at 9:00 AM'],
        ['ready, check overdue', optimization({ nextCheckInHours: -2 }), 'Next check soon'],
        [
            'ready, scout never ran',
            optimization({ lastCheckedHoursAgo: null, nextCheckInHours: null }),
            'First check within a day',
        ],
        [
            'on without an email step to measure',
            optimization({ noSample: true }),
            'Next check around tomorrow at 9:00 AM',
        ],
    ])('%s', (_name, input, headline) => {
        expect(suggestionReadiness(input, NOW)?.headline).toEqual(headline)
    })

    it('marks only the unfinished steps as waiting', () => {
        const readiness = suggestionReadiness(optimization({ trackedSends: 12 }), NOW)
        expect(readiness?.steps.map((step) => [step.key, step.state, step.percent])).toEqual([
            ['enabled', 'done', null],
            ['age', 'done', null],
            ['sends', 'waiting', 60],
            ['check', 'waiting', null],
        ])
    })
})
