import { dayjs } from 'lib/dayjs'

import type { HogFlowOptimizationApi } from '../../generated/api.schemas'
import { showSuggestionReadiness, suggestionReadiness } from './suggestionReadiness'

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
        [
            'off, before any data',
            optimization({ enabled: false, trackedSends: 4 }),
            'Turn on suggestions to start',
            'You can turn them on now. PostHog starts suggesting once the steps below are done.',
        ],
        [
            'short on sends and too new',
            optimization({ trackedSends: 12, liveHoursAgo: 30 }),
            'Needs 8 more emails with open tracking',
            'Suggestions can start after that, and no earlier than tomorrow around 9:00 AM.',
        ],
        [
            'one send short',
            optimization({ trackedSends: 19 }),
            'Needs 1 more email with open tracking',
            'Suggestions can start at the first check after that.',
        ],
        [
            'enough sends on a version under two days old',
            optimization({ liveHoursAgo: 30 }),
            'Can be judged from tomorrow at 9:00 AM',
            'Suggestions can start at the first check after that.',
        ],
        ['ready, checked before', optimization({}), 'Next check tomorrow around 9:00 AM', 'Last checked 6 hours ago.'],
        [
            'ready, check just overdue',
            optimization({ nextCheckInHours: -2 }),
            'Next check soon',
            'Last checked 6 hours ago.',
        ],
        [
            'ready, check long overdue',
            optimization({ lastCheckedHoursAgo: 40, nextCheckInHours: -16 }),
            'Waiting for the next check',
            'Last checked 2 days ago.',
        ],
        [
            'ready, on a cron schedule after a check',
            optimization({ nextCheckInHours: null }),
            'Waiting for the next check',
            'Last checked 6 hours ago.',
        ],
        [
            'ready, scout never ran',
            optimization({ lastCheckedHoursAgo: null, nextCheckInHours: null }),
            'First check within a day',
            null,
        ],
        [
            'on, sample unknown',
            optimization({ noSample: true }),
            'Next check tomorrow around 9:00 AM',
            'Last checked 6 hours ago.',
        ],
    ])('%s', (_name, input, headline, detail) => {
        const readiness = suggestionReadiness(input, NOW)
        expect([readiness?.headline, readiness?.detail]).toEqual([headline, detail])
    })

    test.each([
        [
            'on, short on sends',
            optimization({ trackedSends: 12 }),
            [
                ['age', 'done', null],
                ['sends', 'waiting', 60],
                ['check', 'waiting', null],
            ],
        ],
        [
            'off, short on sends',
            optimization({ enabled: false, trackedSends: 12, liveHoursAgo: 24 }),
            [
                ['enabled', 'blocked', null],
                ['age', 'waiting', 50],
                ['sends', 'waiting', 60],
                ['check', 'blocked', null],
            ],
        ],
        ['on, sample unknown', optimization({ noSample: true }), [['check', 'waiting', null]]],
    ])('steps when %s', (_name, input, steps) => {
        expect(suggestionReadiness(input, NOW)?.steps.map((step) => [step.key, step.state, step.percent])).toEqual(
            steps
        )
    })

    it('does not claim missing data when the sample is unknown', () => {
        const check = suggestionReadiness(optimization({ noSample: true }), NOW)?.steps.find(
            (step) => step.key === 'check'
        )
        expect(check?.detail).toEqual('Last checked 6 hours ago.')
    })

    test.each([
        ['on, scout running', { enabled: true, scout_status: 'running' }, undefined, true],
        ['on, no scout', { enabled: true, scout_status: 'not_running' }, undefined, false],
        ['on, scout paused', { enabled: true, scout_status: 'paused_by_user' }, undefined, false],
        ['on, scout in dry run', { enabled: true, scout_status: 'dry_run' }, undefined, false],
        ['off, no scout yet', { enabled: false, scout_status: 'not_running' }, undefined, true],
        ['off, switch disabled', { enabled: false, scout_status: 'not_running' }, 'Publish first', false],
    ] as const)('shows the card when %s: %s', (_name, status, disabledReason, shown) => {
        expect(showSuggestionReadiness({ ...optimization({}), ...status }, disabledReason)).toBe(shown)
    })
})
