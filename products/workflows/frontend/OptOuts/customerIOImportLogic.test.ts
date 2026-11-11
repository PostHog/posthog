import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { customerIOImportLogic } from './customerIOImportLogic'

const STEP_OPTIONS = [
    { key: 'categories', label: 'Subscription topics', description: '' },
    { key: 'suppressions', label: 'Suppressed addresses', description: '' },
    { key: 'opt_outs', label: 'Global unsubscribes', description: '' },
]

const importRun = (status: ProviderImportRunApi['status']): ProviderImportRunApi => ({
    id: 'run-1',
    provider: 'customerio',
    status,
    steps: [
        {
            key: 'suppressions',
            label: 'Suppressed addresses',
            status: status === 'completed' ? 'completed' : 'running',
            processed: 1000,
            imported: 1000,
            warnings: [],
            last_error: null,
        },
    ],
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:01Z',
    finished_at: status === 'completed' ? '2026-01-01T00:05:00Z' : null,
})

describe('customerIOImportLogic', () => {
    let logic: ReturnType<typeof customerIOImportLogic.build>
    let runResponses: [number, ProviderImportRunApi[] | { detail: string }][]
    let listCalls: number
    let startBodies: Record<string, unknown>[]

    beforeEach(() => {
        runResponses = [
            [200, []],
            [500, { detail: 'boom' }],
            [200, [importRun('completed')]],
        ]
        listCalls = 0
        startBodies = []
        useMocks({
            get: {
                '/api/environments/:team_id/messaging_categories/optout_sync_config/': () => [
                    200,
                    { app_integration_id: null },
                ],
                '/api/projects/:team_id/messaging_provider_imports/providers/': () => [
                    200,
                    [{ key: 'customerio', label: 'Customer.io', steps: STEP_OPTIONS }],
                ],
                '/api/projects/:team_id/messaging_provider_imports/': () => {
                    listCalls += 1
                    return runResponses[Math.min(listCalls - 1, runResponses.length - 1)]
                },
            },
            post: {
                '/api/projects/:team_id/messaging_provider_imports/': async ({ request }) => {
                    startBodies.push((await request.json()) as Record<string, unknown>)
                    return [201, importRun('queued')]
                },
            },
        })
        initKeaTests()
        logic = customerIOImportLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('starts the selected steps and polls the run until it finishes, through a failed refresh', async () => {
        await expectLogic(logic, () => logic.actions.openImportModal()).toFinishAllListeners()
        jest.useFakeTimers()
        logic.actions.toggleImportStep('categories')

        await expectLogic(logic, () => logic.actions.startImport({ apiKey: 'app-key' })).toDispatchActions([
            'startImportSuccess',
            'loadImportRunsSuccess',
        ])

        expect(startBodies).toEqual([
            { provider: 'customerio', steps: ['suppressions', 'opt_outs'], api_key: 'app-key' },
        ])
        expect(logic.values.isImportRunActive).toBe(true)

        await jest.advanceTimersByTimeAsync(2000)
        await expectLogic(logic).toDispatchActions(['loadImportRunsFailure'])
        expect(logic.values.isImportRunActive).toBe(true)

        await jest.advanceTimersByTimeAsync(2000)
        await expectLogic(logic).toDispatchActions(['loadImportRunsSuccess'])

        expect(logic.values.latestImportRun?.status).toBe('completed')
        expect(logic.values.stepCompletion.step1).toBe('completed')

        const callsWhenFinished = listCalls
        await jest.advanceTimersByTimeAsync(10000)

        expect(listCalls).toBe(callsWhenFinished)
    })
})
