/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { JourneyRunDetailApi, JourneyRunStepApi } from './generated/api.schemas'
import { userJourneyRunLogic } from './userJourneyRunLogic'

function step(index: number, changes: Partial<JourneyRunStepApi>): JourneyRunStepApi {
    return {
        index,
        step: { type: 'element_click', selector: 'a' },
        status: 'passed',
        failure_reason: null,
        message: '',
        screenshot_url: `https://storage.example.com/${index}.png`,
        baseline_screenshot_url: `https://storage.example.com/baseline-${index}.png`,
        diff_screenshot_url: null,
        diff_percentage: 0,
        visual_change: 'unchanged',
        duration_ms: 300,
        ...changes,
    }
}

const FAILED_RUN: JourneyRunDetailApi = {
    id: 'run-1',
    team_id: 997,
    journey_id: 'journey-1',
    trigger: 'deploy',
    status: 'failed',
    start_url: 'https://example.com/pricing',
    base_url: null,
    commit_sha: '4f2a9c1d',
    branch: 'add-nav-item',
    viewport_width: 1280,
    viewport_height: 800,
    error: null,
    baseline_run_id: 'run-0',
    created_by_id: null,
    created_at: '2026-11-20T10:00:00Z',
    started_at: '2026-11-20T10:00:01Z',
    finished_at: '2026-11-20T10:00:31Z',
    deploy_id: null,
    failed_step_index: 1,
    failure_reason: 'element_not_visible',
    steps: [
        step(0, { visual_change: 'changed', diff_percentage: 3.2 }),
        step(1, { status: 'failed', failure_reason: 'element_not_visible', visual_change: 'changed' }),
        step(2, { status: 'skipped', screenshot_url: null, baseline_screenshot_url: null, visual_change: null }),
        step(3, {}),
    ],
}

describe('userJourneyRunLogic', () => {
    let logic: ReturnType<typeof userJourneyRunLogic.build>
    let runRequests: number

    beforeEach(() => {
        runRequests = 0
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/user_journeys/:journey_id/runs/:id/': () => {
                    runRequests += 1
                    return [200, FAILED_RUN]
                },
                '/api/projects/:team_id/user_journeys/:id/': { id: 'journey-1', name: 'Sign up', steps: [] },
            },
        })
        logic = userJourneyRunLogic({ id: 'journey-1', runId: 'run-1' })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('opens only the failed step, ahead of earlier visual changes, and lets the reader open others', async () => {
        await expectLogic(logic).toDispatchActions(['loadRunSuccess'])

        expect(logic.values.focusedStepIndex).toBe(1)
        expect(logic.values.summary).toBe('Failed at step 2: element not visible')
        expect([...logic.values.openStepIndexes]).toEqual([1])

        logic.actions.setStepOpen(0, true)
        logic.actions.setStepOpen(1, false)
        expect([...logic.values.openStepIndexes]).toEqual([0])
    })

    it('refetches the run once for fresh screenshot URLs, then reports them unavailable', async () => {
        await expectLogic(logic).toDispatchActions(['loadRunSuccess'])
        expect(runRequests).toBe(1)

        // The baseline and the current image of one step usually break together.
        logic.actions.screenshotFailedToLoad()
        logic.actions.screenshotFailedToLoad()
        await expectLogic(logic).toDispatchActions(['loadRunSuccess'])
        expect(runRequests).toBe(2)
        expect(logic.values.screenshotUrls).toBe('refetched')

        logic.actions.screenshotFailedToLoad()
        await expectLogic(logic).toFinishAllListeners()
        expect(runRequests).toBe(2)
        expect(logic.values.screenshotUrls).toBe('unavailable')
    })
})
