import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { customerIOImportLogic } from './customerIOImportLogic'
import { providerImportLogic } from './providerImportLogic'

const STEP_OPTIONS = [
    { key: 'categories', label: 'Subscription topics', description: '' },
    { key: 'suppressions', label: 'Suppressed addresses', description: '' },
    { key: 'opt_outs', label: 'Global unsubscribes', description: '' },
]

const PROVIDER_OPTION = {
    key: 'customerio',
    label: 'Customer.io',
    steps: STEP_OPTIONS,
    retains_credentials: true,
    api_key_label: 'App API key',
    api_key_help: '',
    api_key_url: null,
    not_imported: '',
    next_steps: [],
}

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
            counts: [],
            items: [],
            warnings_omitted: 0,
            items_omitted: 0,
        },
    ],
    created_at: '2026-01-01T00:00:00Z',
    started_at: '2026-01-01T00:00:01Z',
    finished_at: status === 'completed' ? '2026-01-01T00:05:00Z' : null,
})

describe('providerImportLogic', () => {
    let logic: ReturnType<typeof providerImportLogic.build>
    let customerIOLogic: ReturnType<typeof customerIOImportLogic.build>
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
                '/api/projects/:team_id/messaging_provider_imports/providers/': () => [200, [PROVIDER_OPTION]],
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
        logic = providerImportLogic()
        logic.mount()
        customerIOLogic = customerIOImportLogic()
        customerIOLogic.mount()
    })

    afterEach(() => {
        customerIOLogic.unmount()
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
        expect(customerIOLogic.values.stepCompletion.step1).toBe('completed')

        const callsWhenFinished = listCalls
        await jest.advanceTimersByTimeAsync(10000)

        expect(listCalls).toBe(callsWhenFinished)
    })

    it('asks which tool to import from only when there is more than one', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.selectedProvider?.key).toBe('customerio')

        const resend = { ...PROVIDER_OPTION, key: 'resend', label: 'Resend', retains_credentials: false }
        logic.actions.loadImportProvidersSuccess([PROVIDER_OPTION, resend] as any)
        expect(logic.values.selectedProvider).toBeNull()

        logic.actions.selectProvider('resend')
        expect(logic.values.selectedProvider?.key).toBe('resend')
    })
})
