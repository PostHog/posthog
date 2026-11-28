/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { JourneyRunApi, JourneyRunStatusEnumApi } from './generated/api.schemas'
import { RUN_POLL_INTERVAL_MS } from './journeyRuns'
import { userJourneyRunsLogic } from './userJourneyRunsLogic'

const JOURNEY_ID = 'journey-1'

function run(id: string, status: JourneyRunStatusEnumApi): JourneyRunApi {
    return {
        id,
        team_id: 997,
        journey_id: JOURNEY_ID,
        trigger: 'manual',
        status,
        start_url: 'https://example.com/pricing',
        base_url: null,
        commit_sha: null,
        branch: null,
        viewport_width: 1280,
        viewport_height: 800,
        error: null,
        baseline_run_id: null,
        created_by_id: 1,
        created_at: '2026-11-20T10:00:00Z',
        started_at: '2026-11-20T10:00:01Z',
        finished_at: status === 'pending' || status === 'running' ? null : '2026-11-20T10:00:31Z',
        deploy_id: null,
        failed_step_index: status === 'failed' ? 1 : null,
        failure_reason: status === 'failed' ? 'element_not_visible' : null,
    }
}

const OLDER_FAILED_RUN = run('failed-run', 'failed')
describe('userJourneyRunsLogic', () => {
    let logic: ReturnType<typeof userJourneyRunsLogic.build>
    let listRequests: number

    beforeEach(() => {
        listRequests = 0
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.useRealTimers()
    })

    function mockRuns(pages: JourneyRunApi[][]): void {
        useMocks({
            get: {
                '/api/projects/:team_id/user_journeys/:journey_id/runs/': () => {
                    const results = pages[Math.min(listRequests, pages.length - 1)]
                    listRequests += 1
                    return [200, { count: results.length, results }]
                },
            },
        })
    }

    it('polls while a run is in progress and stops once it settles', async () => {
        jest.useFakeTimers()
        mockRuns([
            [run('new-run', 'running'), OLDER_FAILED_RUN],
            [run('new-run', 'passed'), OLDER_FAILED_RUN],
        ])
        logic = userJourneyRunsLogic({ journeyId: JOURNEY_ID })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(listRequests).toBe(1)
        expect(logic.values.activeRun?.id).toBe('new-run')

        await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS)
        expect(listRequests).toBe(2)
        expect(logic.values.activeRun).toBeNull()

        await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 5)
        expect(listRequests).toBe(2)
    })

    it('stops polling when the journey closes', async () => {
        jest.useFakeTimers()
        mockRuns([[run('new-run', 'pending')]])
        logic = userJourneyRunsLogic({ journeyId: JOURNEY_ID })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(listRequests).toBe(1)

        logic.unmount()
        await jest.advanceTimersByTimeAsync(RUN_POLL_INTERVAL_MS * 5)
        expect(listRequests).toBe(1)
    })

    async function startRunAnswered(status: number, body: Record<string, unknown>): Promise<void> {
        mockRuns([[], [run('deploy-run', 'running')]])
        useMocks({ post: { '/api/projects/:team_id/user_journeys/:journey_id/runs/': () => [status, body] } })
        logic = userJourneyRunsLogic({ journeyId: JOURNEY_ID })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadRunsSuccess'])

        logic.actions.setBaseUrl('https://preview.example.org')
        await expectLogic(logic, () => logic.actions.startRun()).toDispatchActions(['startRunFailure'])
    }

    it('shows the server message when the run is rejected', async () => {
        const detail = "preview.example.org isn't one of this project's authorized URLs."
        await startRunAnswered(400, { type: 'validation_error', code: 'invalid', detail, attr: 'base_url' })

        expect(logic.values).toMatchObject({ startRunError: detail, runConflict: false, startingRun: false })
    })

    it('points at the run in progress when another run is going', async () => {
        await startRunAnswered(409, { type: 'conflict', code: 'conflict', detail: 'A run is in progress.' })
        await expectLogic(logic).toDispatchActions(['loadRunsSuccess'])

        expect(logic.values).toMatchObject({ startRunError: null, runConflict: true, startingRun: false })
        expect(logic.values.activeRun?.id).toBe('deploy-run')
    })
})
