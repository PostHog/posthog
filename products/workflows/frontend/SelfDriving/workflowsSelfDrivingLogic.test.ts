import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { workflowsSelfDrivingLogic } from './workflowsSelfDrivingLogic'

const FATIGUE_SCOUT = 'signals-scout-workflows-fatigue'

function scoutConfig(overrides: Partial<SignalScoutConfigApi> = {}): SignalScoutConfigApi {
    return {
        id: 'config-1',
        skill_name: FATIGUE_SCOUT,
        display_name: 'Workflows audience fatigue',
        description: '',
        enabled: false,
        status: 'paused_by_user',
        emit: true,
        run_interval_minutes: 1440,
        run_cron_schedule: null,
        last_run_at: null,
        tags: ['workflows'],
        ...overrides,
    } as SignalScoutConfigApi
}

describe('workflowsSelfDrivingLogic', () => {
    let logic: ReturnType<typeof workflowsSelfDrivingLogic.build>
    let configs: SignalScoutConfigApi[]
    let configsFail: boolean
    let syncCalls: number
    let patchFails: boolean
    let patchCalls: { id: string; body: Record<string, unknown> }[]
    let reportQueries: string[]

    beforeEach(() => {
        configs = [scoutConfig()]
        configsFail = false
        syncCalls = 0
        patchFails = false
        patchCalls = []
        reportQueries = []
        useMocks({
            get: {
                '/api/projects/:team_id/signals/scout/configs/': () => (configsFail ? [500, {}] : [200, configs]),
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    reportQueries.push(new URL(request.url).searchParams.get('scout') ?? '')
                    return [
                        200,
                        {
                            count: 1,
                            results: [
                                {
                                    id: 'report-1',
                                    title: 'Two workflows reach the same people this week',
                                    summary: null,
                                    status: 'ready',
                                    priority: 'P3',
                                    created_at: '2026-09-01T00:00:00Z',
                                    updated_at: '2026-09-01T00:00:00Z',
                                },
                            ],
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team_id/signals/scout/configs/sync/': () => {
                    syncCalls += 1
                    return [200, []]
                },
            },
            patch: {
                '/api/projects/:team_id/signals/scout/configs/:id/': async ({ request, params }) => {
                    if (patchFails) {
                        return [500, {}]
                    }
                    const id = params.id as string
                    const body = (await request.json()) as Record<string, unknown>
                    patchCalls.push({ id, body })
                    configs = configs.map((config) => (config.id === id ? { ...config, ...body } : config))
                    return [200, configs.find((config) => config.id === id)]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mountLogic(): void {
        logic = workflowsSelfDrivingLogic()
        logic.mount()
    }

    it('reads the opt-in from the workflows-tagged scouts and loads only their suggestions', async () => {
        mountLogic()

        await expectLogic(logic)
            .toDispatchActions(['loadScoutConfigsSuccess', 'loadSuggestionsSuccess'])
            .toMatchValues({ availability: 'available', selfDrivingEnabled: false })

        expect(reportQueries).toEqual([FATIGUE_SCOUT])
        expect(syncCalls).toBe(0)
    })

    it('syncs the fleet once when no workflows scout is registered, then reports unavailable', async () => {
        configs = []
        mountLogic()

        await expectLogic(logic)
            .toDispatchActions(['loadScoutConfigsSuccess', 'syncScoutConfigs', 'syncScoutConfigsSuccess'])
            .toMatchValues({ availability: 'unavailable', selfDrivingEnabled: false })

        expect(syncCalls).toBe(1)
        expect(reportQueries).toEqual([])
    })

    it('reports an error instead of loading forever when the scout list cannot be read', async () => {
        configsFail = true
        mountLogic()

        await expectLogic(logic).toDispatchActions(['loadScoutConfigsFailure']).toMatchValues({ availability: 'error' })

        expect(syncCalls).toBe(0)
    })

    it('turning on Self-driving enables the disabled scouts, reloads them, and clears the in-flight state', async () => {
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadScoutConfigsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.turnOnSelfDriving()
        })
            .toDispatchActions(['turnOnSelfDriving', 'loadScoutConfigsSuccess', 'turnOnSelfDrivingFinished'])
            .toMatchValues({ selfDrivingEnabled: true, turningOn: false })

        expect(patchCalls).toEqual([{ id: 'config-1', body: { enabled: true } }])
    })

    it('a failed scout update keeps the previous settings and clears the updating state', async () => {
        patchFails = true
        mountLogic()
        await expectLogic(logic).toDispatchActions(['loadScoutConfigsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.updateScoutConfig('config-1', { enabled: true })
        })
            .toDispatchActions(['setScoutUpdating', 'setScoutUpdating'])
            .toMatchValues({ updatingScoutIds: [], selfDrivingEnabled: false })
    })
})
