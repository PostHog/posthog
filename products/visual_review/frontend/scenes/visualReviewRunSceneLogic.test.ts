import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { visualReviewRunSceneLogic } from './visualReviewRunSceneLogic'

const RUN_ID = '00000000-0000-0000-0000-0000000000aa'
const TOLERATED_URL = `/api/projects/:team_id/visual_review/runs/${RUN_ID}/tolerated-hashes/`

const toleratedToday = (index: number): Record<string, unknown> => ({
    id: `tolerated-${index}`,
    alternate_hash: `alt-${index}`,
    baseline_hash: 'base',
    reason: 'human',
    diff_percentage: 2.6,
    created_at: new Date().toISOString(),
    source_run_id: null,
})

describe('visualReviewRunSceneLogic', () => {
    let logic: ReturnType<typeof visualReviewRunSceneLogic.build>
    let releaseSlow: () => void = () => {}

    beforeEach(() => {
        useMocks({
            get: {
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/`]: [404, {}],
                [`/api/projects/:team_id/visual_review/runs/${RUN_ID}/snapshots/`]: [404, {}],
                [TOLERATED_URL]: async ({ request }) => {
                    const identifier = new URL(request.url).searchParams.get('identifier')
                    if (identifier === 'other') {
                        return [500, {}]
                    }
                    if (identifier?.startsWith('slow')) {
                        await new Promise<void>((resolve) => {
                            releaseSlow = resolve
                        })
                    }
                    if (identifier === 'slow-failing') {
                        return [500, {}]
                    }
                    const results = identifier === 'quiet' ? [] : [0, 1, 2].map(toleratedToday)
                    return [200, { count: results.length, next: null, previous: null, results }]
                },
            },
        })
        initKeaTests()
        logic = visualReviewRunSceneLogic({ runId: RUN_ID })
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('drops the previous snapshot tolerations when the next load fails', async () => {
        await expectLogic(logic, () => logic.actions.loadToleratedHashes('flaky'))
            .toDispatchActions(['loadToleratedHashesSuccess'])
            .toMatchValues({ recentTolerations: { manual: 3, agent: 0, auto: 0 } })

        await expectLogic(logic, () => logic.actions.loadToleratedHashes('other'))
            .toDispatchActions(['loadToleratedHashesFailure'])
            .toMatchValues({ recentTolerations: { manual: 0, agent: 0, auto: 0 } })
    })

    it.each([
        { slow: 'slow', fast: 'quiet', manual: 0 },
        { slow: 'slow-failing', fast: 'flaky', manual: 3 },
    ])('ignores a $slow response that lands after $fast', async ({ slow, fast, manual }) => {
        logic.actions.loadToleratedHashes(slow)
        await expectLogic(logic, () => logic.actions.loadToleratedHashes(fast))
            .toDispatchActions(['loadToleratedHashesSuccess'])
            .toMatchValues({ recentTolerations: { manual, agent: 0, auto: 0 } })

        releaseSlow()
        await expectLogic(logic).toFinishAllListeners()
        await expectLogic(logic).toMatchValues({ recentTolerations: { manual, agent: 0, auto: 0 } })
    })
})
