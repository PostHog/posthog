import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

const RUN_ID = '00000000-0000-0000-0000-0000000000aa'
const RUN_URL = `/api/projects/:team_id/visual_review/runs/${RUN_ID}/`
const SNAPSHOTS_URL = `${RUN_URL}snapshots/`

const failWith = (status: number): Record<string, () => [number, { detail: string }]> => ({
    [RUN_URL]: () => [status, { detail: 'Run not found' }],
    [SNAPSHOTS_URL]: () => [status, { detail: 'Run not found' }],
})

describe('visualReviewRunSceneLogic', () => {
    let logic: ReturnType<typeof visualReviewRunSceneLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    // A run link from a PR carries a project id the router strips, so the request goes to
    // whichever project is active and answers 404. Every failed load leaves `run` null, which
    // is also what the first fetch looks like, so the scene needs the 404 called out.
    describe('when the run answers 404', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({ get: failWith(404) })
            logic = visualReviewRunSceneLogic({ runId: RUN_ID })
            logic.mount()
        })

        it('reports the run as not found', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.run).toBeNull()
            expect(logic.values.runNotFound).toBe(true)
        })

        it('stops reporting it once the run is loaded again', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.runNotFound).toBe(true)

            logic.actions.loadRun()
            expect(logic.values.runNotFound).toBe(false)
        })
    })

    describe('when the run load fails for another reason', () => {
        beforeEach(() => {
            initKeaTests()
            useMocks({ get: failWith(500) })
            logic = visualReviewRunSceneLogic({ runId: RUN_ID })
            logic.mount()
        })

        it('does not report the run as not found', async () => {
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.runNotFound).toBe(false)
        })
    })
})
