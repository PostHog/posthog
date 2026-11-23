import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { suppressionListLogic } from '../Suppression/suppressionListLogic'
import { messageTemplatesLogic } from '../TemplateLibrary/messageTemplatesLogic'
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
    settings: [],
}

const PROVIDER_WITH_SETTINGS = {
    ...PROVIDER_OPTION,
    key: 'resend',
    label: 'Resend',
    retains_credentials: false,
    settings: [
        { key: 'region', label: 'Region', help: '', default: null, choices: [{ value: 'eu', label: 'EU' }] },
        {
            key: 'template_versions',
            label: 'Template versions',
            help: '',
            default: 'active',
            choices: [{ value: 'active', label: 'Active' }],
        },
    ],
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
    settings: {},
})

describe('providerImportLogic', () => {
    let logic: ReturnType<typeof providerImportLogic.build>
    let customerIOLogic: ReturnType<typeof customerIOImportLogic.build>
    let runResponses: [number, ProviderImportRunApi[] | { detail: string }][]
    let listCalls: number
    let retrieved: ProviderImportRunApi
    let startBodies: Record<string, unknown>[]

    beforeEach(() => {
        runResponses = [
            [200, []],
            [500, { detail: 'boom' }],
            [200, [importRun('completed')]],
        ]
        listCalls = 0
        retrieved = importRun('completed')
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
                '/api/projects/:team_id/messaging_provider_imports/:id/': () => [200, retrieved],
                '/api/environments/:team_id/messaging_templates/': () => [200, { results: [] }],
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

    it('holds the start until a setting with no default is chosen, then sends it with the defaults', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_provider_imports/providers/': () => [
                    200,
                    [PROVIDER_OPTION, PROVIDER_WITH_SETTINGS],
                ],
            },
        })
        logic.actions.loadImportProviders()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.selectProvider('resend')
        expect(logic.values.missingImportSetting?.key).toEqual('region')

        logic.actions.setImportSetting('region', 'eu')
        expect(logic.values.missingImportSetting).toBeNull()
        logic.actions.startImport({ apiKey: 'key' })
        await expectLogic(logic).toFinishAllListeners()

        expect(startBodies[0].settings).toEqual({ region: 'eu', template_versions: 'active' })

        logic.actions.selectProvider('customerio')
        expect(logic.values.importSettings).toEqual({})
    })

    it('blocks the start as soon as a ticked step loses a step it needs', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_provider_imports/providers/': () => [
                    200,
                    [
                        {
                            ...PROVIDER_WITH_SETTINGS,
                            settings: [],
                            steps: [
                                { key: 'suppressions', label: 'Suppression list', description: '', needs: [] },
                                { key: 'opt_outs', label: 'Unsubscribed contacts', description: '', needs: [] },
                                {
                                    key: 'contacts',
                                    label: 'Contacts',
                                    description: '',
                                    needs: ['suppressions', 'opt_outs'],
                                },
                            ],
                        },
                    ],
                ],
            },
        })
        logic.actions.loadImportProviders()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.cannotStartImportReason).toBeNull()

        logic.actions.toggleImportStep('suppressions')
        logic.actions.toggleImportStep('opt_outs')

        expect(logic.values.unmetStepNeeds).toEqual({ contacts: ['Suppression list', 'Unsubscribed contacts'] })
        expect(logic.values.cannotStartImportReason).toEqual(
            'Contacts needs Suppression list and Unsubscribed contacts selected too'
        )
        logic.actions.setImportFormValue('api_key', 're_key')
        logic.actions.submitImportForm()
        await expectLogic(logic).toFinishAllListeners()
        expect(startBodies).toEqual([])

        logic.actions.toggleImportStep('suppressions')
        expect(logic.values.unmetStepNeeds).toEqual({ contacts: ['Unsubscribed contacts'] })

        logic.actions.toggleImportStep('opt_outs')
        expect(logic.values.cannotStartImportReason).toBeNull()

        logic.actions.setImportFormValue('api_key', '   ')
        logic.actions.submitImportForm()
        await expectLogic(logic).toFinishAllListeners()
        expect(startBodies).toEqual([])
    })

    it('reloads the suppression list behind the window when it closes during an import', async () => {
        let suppressionLoads = 0
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_suppressions/suppressions/': () => {
                    suppressionLoads += 1
                    return [200, { count: 0, next: null, previous: null, results: [] }]
                },
            },
        })
        const suppressions = suppressionListLogic()
        await expectLogic(suppressions, () => {
            suppressions.mount()
        }).toDispatchActions(['loadSuppressionsSuccess'])
        expect(suppressionLoads).toBe(1)

        logic.actions.closeImportModal()
        await expectLogic(suppressions).toFinishAllListeners()
        expect(suppressionLoads).toBe(1)

        logic.actions.setTrackedImportRunIds(['run-1'])
        await expectLogic(suppressions, () => logic.actions.closeImportModal()).toDispatchActions([
            'loadSuppressionsSuccess',
        ])
        expect(suppressionLoads).toBe(2)
        suppressions.unmount()
    })

    it('starts the selected steps and polls the run until it finishes, through a failed refresh', async () => {
        const templatesLogic = messageTemplatesLogic()
        await expectLogic(templatesLogic, () => {
            templatesLogic.mount()
        }).toDispatchActions(['loadTemplatesSuccess'])
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
        await expectLogic(templatesLogic).toDispatchActions(['loadTemplates'])
        templatesLogic.unmount()

        const callsWhenFinished = listCalls
        await jest.advanceTimersByTimeAsync(10000)

        expect(listCalls).toBe(callsWhenFinished)
    })

    it('follows a running import that dropped out of the recent list until it ends', async () => {
        runResponses = [[200, []]]
        await expectLogic(logic, () => logic.actions.openImportModal()).toFinishAllListeners()
        jest.useFakeTimers()
        await expectLogic(logic, () => logic.actions.startImport({ apiKey: 'app-key' })).toDispatchActions([
            'startImportSuccess',
            'loadImportRunsSuccess',
        ])

        await jest.advanceTimersByTimeAsync(2000)
        await expectLogic(logic).toDispatchActions(['loadImportRunsSuccess'])

        expect(logic.values.latestImportRun?.status).toBe('completed')
        expect(logic.values.isImportRunActive).toBe(false)
    })

    it.each([
        [true, 0],
        [false, 1],
    ])('toasts a refused start only when the window is closed (open: %s)', async (keepOpen, toasts) => {
        const toastError = jest.spyOn(lemonToast, 'error')
        useMocks({ post: { '/api/projects/:team_id/messaging_provider_imports/': () => [400, { detail: 'Bad key' }] } })
        await expectLogic(logic, () => logic.actions.openImportModal()).toFinishAllListeners()

        logic.actions.startImport({ apiKey: 'app-key' })
        if (!keepOpen) {
            logic.actions.closeImportModal()
        }
        await expectLogic(logic).toDispatchActions(['startImportFailure'])

        expect(toastError).toHaveBeenCalledTimes(toasts)
        toastError.mockRestore()
    })

    it("keeps a refused start out of another tool's form", async () => {
        const toastError = jest.spyOn(lemonToast, 'error')
        useMocks({ post: { '/api/projects/:team_id/messaging_provider_imports/': () => [400, { detail: 'Bad key' }] } })
        await expectLogic(logic, () => logic.actions.openImportModal()).toFinishAllListeners()
        const resend = { ...PROVIDER_OPTION, key: 'resend', label: 'Resend', retains_credentials: false }
        logic.actions.loadImportProvidersSuccess([PROVIDER_OPTION, resend] as any)
        logic.actions.selectProvider('customerio')

        logic.actions.startImport({ apiKey: 'app-key' })
        logic.actions.selectProvider('resend')
        logic.actions.setImportFormValue('api_key', 'a-resend-key')
        await expectLogic(logic).toDispatchActions(['startImportFailure'])

        expect(logic.values.importError).toBeNull()
        expect(logic.values.importForm.api_key).toBe('a-resend-key')
        expect(toastError).toHaveBeenCalledWith('Bad key')
        toastError.mockRestore()
    })

    it('keeps a run started while a refresh was in flight', async () => {
        let olderRunRequested: () => void = () => {}
        const fetchingOlderRun = new Promise<void>((resolve) => {
            olderRunRequested = resolve
        })
        let finishOlderRun: () => void = () => {}
        const olderRunFinished = new Promise<void>((resolve) => {
            finishOlderRun = resolve
        })
        useMocks({
            get: {
                '/api/projects/:team_id/messaging_provider_imports/': () => [200, []],
                '/api/projects/:team_id/messaging_provider_imports/:id/': async () => {
                    olderRunRequested()
                    await olderRunFinished
                    return [200, importRun('completed')]
                },
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setTrackedImportRunIds(['run-1'])

        logic.actions.loadImportRuns()
        await fetchingOlderRun
        logic.actions.startImportSuccess({ ...importRun('running'), id: 'run-2' })
        finishOlderRun()
        await expectLogic(logic).toDispatchActions(['loadImportRunsSuccess', 'loadImportRunsSuccess'])

        expect(logic.values.importRuns?.map((run) => run.id)).toEqual(['run-2', 'run-1'])
        expect(logic.values.trackedImportRunIds).toEqual(['run-2'])
    })

    it('asks which tool to import from only when there is more than one', async () => {
        expect(logic.values.importButtonLabel).toBe('Import from another tool')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.selectedProvider?.key).toBe('customerio')
        expect(logic.values.importButtonLabel).toBe('Import from Customer.io')

        const resend = { ...PROVIDER_OPTION, key: 'resend', label: 'Resend', retains_credentials: false }
        logic.actions.loadImportProvidersSuccess([PROVIDER_OPTION, resend] as any)
        expect(logic.values.selectedProvider).toBeNull()
        expect(logic.values.importButtonLabel).toBe('Import from another tool')

        logic.actions.setImportFormValue('api_key', 'a-key-for-another-tool')
        logic.actions.selectProvider('resend')
        expect(logic.values.selectedProvider?.key).toBe('resend')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.importForm.api_key).toBe('')
    })

    it.each([
        ['workflows', true],
        ['templates', true],
        ['transactional', false],
    ] as const)(
        'opens straight on Customer.io from the %s page when it is the only tool, with automations: %s',
        async (entryPoint, showsAutomationImport) => {
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.openImportModal(null, entryPoint)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.showsAutomationImport).toBe(showsAutomationImport)
            expect(logic.values.selectedProvider?.key).toBe('customerio')
        }
    )

    it('lists the tools by name, whatever order the API sends', () => {
        const tool = (key: string, label: string): typeof PROVIDER_OPTION => ({ ...PROVIDER_OPTION, key, label })
        logic.actions.loadImportProvidersSuccess([
            tool('sendgrid', 'SendGrid'),
            PROVIDER_OPTION,
            tool('resend', 'Resend'),
            tool('mailgun', 'Mailgun'),
            tool('a-postmark', 'Postmark'),
        ] as any)

        expect(logic.values.orderedImportProviders.map((provider) => provider.label)).toEqual([
            'Customer.io',
            'Mailgun',
            'Postmark',
            'Resend',
            'SendGrid',
        ])
    })
})
