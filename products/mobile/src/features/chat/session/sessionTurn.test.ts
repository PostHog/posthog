import { initialRunState } from '@/features/handoff/runStream'
import type { RunStreamState } from '@/features/handoff/types'
import { setAnalyticsClient } from '@/lib/analytics'

import { SessionTurnTracker } from './sessionTurn'

const ENDED: RunStreamState = { ...initialRunState('task-1', 'run-1', 'in_progress'), turnEnded: true }
const WORKING: RunStreamState = { ...ENDED, turnEnded: false, phase: 'working' }

describe('SessionTurnTracker', () => {
    const capture = jest.fn()
    beforeEach(() => {
        setAnalyticsClient({ capture, identify: jest.fn(), reset: jest.fn() })
    })
    afterEach(() => {
        setAnalyticsClient(null)
        capture.mockClear()
    })

    test.each<[string, (tracker: SessionTurnTracker) => void, string]>([
        ['a turn that ends', (tracker) => tracker.observe(ENDED), 'completed'],
        [
            'a stopped turn',
            (tracker) => {
                tracker.markStopped(true)
                tracker.observe(ENDED)
            },
            'stopped',
        ],
        ['a run that fails', (tracker) => tracker.observe({ ...WORKING, status: 'failed' }), 'failed'],
        ['a chat that drops the turn', (tracker) => tracker.finish('abandoned'), 'abandoned'],
    ])('%s finishes once, after the previous turn end is ignored', (_name, end, status) => {
        let now = 1_000
        const tracker = new SessionTurnTracker(() => now)
        // A follow-up demo send starts from the previous turn's end, which must not finish the new turn.
        tracker.begin(ENDED)
        tracker.observe(ENDED)
        expect(capture).not.toHaveBeenCalled()
        tracker.observe({ ...WORKING, pending: { record: {} as never, kind: 'question', replayed: false } })
        now = 13_400
        end(tracker)
        tracker.observe(ENDED)
        tracker.finish('abandoned')

        expect(capture.mock.calls).toEqual([
            ['mobile_session_finished', { status, duration_s: 12, had_decision: true }],
        ])
    })
})
