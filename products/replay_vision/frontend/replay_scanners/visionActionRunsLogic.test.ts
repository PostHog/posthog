import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionActionApi, VisionActionRunListApi } from '../generated/api.schemas'
import { visionActionRunsLogic } from './visionActionRunsLogic'

const run = (id: string, overrides: Partial<VisionActionRunListApi> = {}): VisionActionRunListApi => ({
    id,
    status: 'completed',
    scheduled_at: '2026-01-01T09:00:00Z',
    observation_count: 3,
    error_reason: '',
    created_at: '2026-01-01T09:01:00Z',
    updated_at: '2026-01-01T09:01:00Z',
    ...overrides,
})

const ACTION = {
    id: 'a1',
    name: 'daily summary',
    scanner: 's1',
    trigger_config: { rrule: 'FREQ=DAILY' },
    delivery_config: [],
} as unknown as VisionActionApi

describe('visionActionRunsLogic', () => {
    let logic: ReturnType<typeof visionActionRunsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/actions/:action/': ACTION,
                '/api/projects/:team/vision/actions/:action/runs/': {
                    results: [
                        run('r1'),
                        run('r2', {
                            status: 'skipped',
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

    it('loads the action and its runs on mount', async () => {
        // The action and runs fetch in parallel, so don't assert a strict order — wait for both to settle.
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                action: expect.objectContaining({ id: 'a1', name: 'daily summary' }),
                actionLoading: false,
                runs: expect.arrayContaining([
                    expect.objectContaining({ id: 'r1', status: 'completed' }),
                    expect.objectContaining({ id: 'r2', status: 'skipped' }),
                ]),
                runsCount: 2,
                runsLoading: false,
            })
    })
})
