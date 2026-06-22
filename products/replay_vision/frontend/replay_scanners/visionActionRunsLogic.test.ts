import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionRunApi } from '../generated/api.schemas'
import { visionActionRunsLogic } from './visionActionRunsLogic'

const run = (id: string, overrides: Partial<VisionActionRunApi> = {}): VisionActionRunApi => ({
    id,
    status: 'completed',
    scheduled_at: '2026-01-01T09:00:00Z',
    observation_count: 3,
    synthesized_markdown: '# Themes',
    error_reason: '',
    created_at: '2026-01-01T09:01:00Z',
    updated_at: '2026-01-01T09:01:00Z',
    ...overrides,
})

describe('visionActionRunsLogic', () => {
    let logic: ReturnType<typeof visionActionRunsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:action/runs/': {
                    results: [
                        run('r1'),
                        run('r2', {
                            status: 'skipped',
                            synthesized_markdown: '',
                            error_reason: 'nothing to summarize',
                        }),
                    ],
                    count: 2,
                },
            },
        })
        initKeaTests()
        logic = visionActionRunsLogic({ actionId: 'a1' })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('loads the action runs on mount', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadRuns', 'loadRunsSuccess'])
            .toMatchValues({
                runs: expect.arrayContaining([
                    expect.objectContaining({ id: 'r1', status: 'completed' }),
                    expect.objectContaining({ id: 'r2', status: 'skipped' }),
                ]),
                runsLoading: false,
            })
    })
})
