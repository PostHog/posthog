import { expectLogic } from 'kea-test-utils'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { type RecalculationPayload, experimentMetricsLogic } from 'scenes/experiments/experimentMetricsLogic'
import { projectLogic } from 'scenes/projectLogic'

import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched.json'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Experiment } from '~/types'

import { experimentExposuresWindowLogic } from './experimentExposuresWindowLogic'

const EXPERIMENT = experimentJson as unknown as Experiment
const FIRST_WINDOW = '2024-03-01T12:00:00Z'
const NEXT_WINDOW = '2024-03-02T12:00:00Z'

const run = (status: RecalculationPayload['status'], queryTo: string): RecalculationPayload =>
    ({
        id: `run-${status}-${queryTo}`,
        status,
        total_metrics: 0,
        completed_metrics: 0,
        failed_metrics: 0,
        completed_at: status === 'completed' ? queryTo : null,
        query_to: queryTo,
        results: [],
    }) as unknown as RecalculationPayload

describe('experimentExposuresWindowLogic', () => {
    let logic: ReturnType<typeof experimentExposuresWindowLogic.build>
    let metricsLogic: ReturnType<typeof experimentMetricsLogic.build>
    let mainLogic: ReturnType<typeof experimentLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team/experiments/:id': EXPERIMENT,
                '/api/projects/:team_id/experiments/:id/metrics_recalculation/latest/': () => [
                    200,
                    run('completed', FIRST_WINDOW),
                ],
            },
            post: {
                '/api/environments/:team/query/:kind': () => [200, {}],
            },
        })
        initKeaTests()
        await expectLogic(projectLogic).toMatchValues({ currentProjectId: expect.any(Number) })

        mainLogic = experimentLogic({ experimentId: EXPERIMENT.id })
        mainLogic.mount()
        mainLogic.actions.setExperiment(EXPERIMENT)
        metricsLogic = experimentMetricsLogic({ experiment: EXPERIMENT })
        metricsLogic.mount()
        await expectLogic(metricsLogic).toDispatchActions(['setCurrentRecalculation'])

        logic = experimentExposuresWindowLogic({ experiment: EXPERIMENT })
        logic.mount()
        await expectLogic(mainLogic).toDispatchActions(['loadExposures', 'loadExposuresSuccess'])
        expect(mainLogic.values.exposuresAsOf).toEqual(FIRST_WINDOW)
    })

    afterEach(() => {
        logic.unmount()
        metricsLogic.unmount()
        mainLogic.unmount()
    })

    it.each([
        ['a finished run moves the window', run('completed', NEXT_WINDOW), true],
        ['a partly failed run moves the window', run('failed', NEXT_WINDOW), true],
        ['a run in flight keeps the window', run('in_progress', NEXT_WINDOW), false],
        ['a finished run on the same window', run('completed', FIRST_WINDOW), false],
    ])('%s', async (_, recalculation, reloads) => {
        const assertion = expectLogic(mainLogic, () => {
            metricsLogic.actions.setCurrentRecalculation(recalculation)
        })
        if (reloads) {
            await assertion.toDispatchActions(['loadExposures']).toFinishAllListeners()
            expect(mainLogic.values.exposuresAsOf).toEqual(NEXT_WINDOW)
        } else {
            await assertion.toNotHaveDispatchedActions(['loadExposures'])
            expect(mainLogic.values.exposuresAsOf).toEqual(FIRST_WINDOW)
        }
    })
})
