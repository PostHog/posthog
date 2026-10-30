import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { customerIOImportLogic } from './customerIOImportLogic'
import type { ImportWizardStep, OptOutSyncConfigResponse } from './customerIOImportLogic'
import { ImportScene } from './ImportScene'

const syncConfigEndpoint = '/api/environments/:team_id/messaging_categories/optout_sync_config/'
const importRunsEndpoint = '/api/projects/:team_id/messaging_provider_imports/'
const importProvidersEndpoint = '/api/projects/:team_id/messaging_provider_imports/providers/'

const importProviders = [
    {
        key: 'customerio',
        label: 'Customer.io',
        steps: [
            {
                key: 'categories',
                label: 'Subscription topics',
                description: 'Creates a message category for each Customer.io subscription topic.',
            },
            {
                key: 'suppressions',
                label: 'Suppressed addresses',
                description:
                    "Adds the addresses that Customer.io's email provider bounced, marked as invalid, or got a spam report for to the suppression list.",
            },
            {
                key: 'opt_outs',
                label: 'Global unsubscribes',
                description:
                    'Opts people who unsubscribed from all Customer.io messages out of all marketing messages.',
            },
        ],
    },
]

function mockSyncConfig(
    config: OptOutSyncConfigResponse,
    importRuns: ProviderImportRunApi[] = []
): Record<string, any> {
    return {
        get: {
            [syncConfigEndpoint]: config,
            [importRunsEndpoint]: importRuns,
            [importProvidersEndpoint]: importProviders,
        },
    }
}

const emptySyncConfig: OptOutSyncConfigResponse = {
    app_integration_id: null,
    app_import_result: null,
    csv_import_result: null,
    webhook_enabled: false,
    has_webhook_secret: false,
    track_enabled: false,
    has_track_credentials: false,
}

const importedConfig: OptOutSyncConfigResponse = {
    ...emptySyncConfig,
    app_integration_id: 1,
    app_import_result: {
        status: 'completed',
        imported_at: '2026-04-13T10:00:00Z',
        categories_created: 6,
        globally_unsubscribed_count: 1234,
        suppressions_imported: 2045,
    },
}

const meta: Meta = {
    title: 'Products/Workflows/Import',
    component: ImportScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-13 10:30:00',
    },
}
export default meta

type StoryProps = {
    syncConfig: OptOutSyncConfigResponse
    importRuns?: ProviderImportRunApi[]
    step?: ImportWizardStep
}

const Template: StoryFn<StoryProps> = ({ syncConfig, importRuns, step }) => {
    useStorybookMocks(mockSyncConfig(syncConfig, importRuns))
    const { selectProvider, setStep } = useActions(customerIOImportLogic)

    useEffect(() => {
        if (step && step !== 'provider') {
            selectProvider('customerio')
            setStep(step)
        }
    }, [step, selectProvider, setStep])

    return (
        <div className="p-4">
            <ImportScene />
        </div>
    )
}

const wizardReady = { testOptions: { waitForSelector: '[data-attr="messaging-import-step-provider"]' } }

const storedKeyConfig: OptOutSyncConfigResponse = { ...emptySyncConfig, app_integration_id: 1 }

const syncEnabledConfig: OptOutSyncConfigResponse = {
    ...importedConfig,
    webhook_enabled: true,
    has_webhook_secret: true,
    track_enabled: true,
    has_track_credentials: true,
}

const importRun = (
    status: ProviderImportRunApi['status'],
    steps: ProviderImportRunApi['steps']
): ProviderImportRunApi => ({
    id: 'run-1',
    provider: 'customerio',
    status,
    steps,
    created_at: '2026-04-13T10:00:00Z',
    started_at: '2026-04-13T10:00:02Z',
    finished_at: status === 'completed' || status === 'failed' ? '2026-04-13T10:06:00Z' : null,
})

const completedSteps: ProviderImportRunApi['steps'] = [
    {
        key: 'categories',
        label: 'Subscription topics',
        status: 'completed',
        processed: 6,
        imported: 6,
        warnings: [],
        last_error: null,
    },
    {
        key: 'suppressions',
        label: 'Suppressed addresses',
        status: 'completed',
        processed: 2505,
        imported: 2505,
        warnings: [],
        last_error: null,
    },
    {
        key: 'opt_outs',
        label: 'Global unsubscribes',
        status: 'completed',
        processed: 1234,
        imported: 1234,
        warnings: [],
        last_error: null,
    },
]

export const ChooseProvider: StoryFn<StoryProps> = Template.bind({})
ChooseProvider.args = { syncConfig: emptySyncConfig }
ChooseProvider.parameters = wizardReady

export const Connect: StoryFn<StoryProps> = Template.bind({})
Connect.args = { syncConfig: emptySyncConfig, step: 'connect' }
Connect.parameters = wizardReady

export const ConnectWithSavedKey: StoryFn<StoryProps> = Template.bind({})
ConnectWithSavedKey.args = { syncConfig: storedKeyConfig, step: 'connect' }
ConnectWithSavedKey.parameters = wizardReady

export const ChooseData: StoryFn<StoryProps> = Template.bind({})
ChooseData.args = { syncConfig: storedKeyConfig, step: 'choose' }
ChooseData.parameters = { testOptions: { waitForSelector: '[data-attr="customerio-import-step-categories"]' } }

export const ImportRunning: StoryFn<StoryProps> = Template.bind({})
ImportRunning.args = {
    syncConfig: storedKeyConfig,
    importRuns: [
        importRun('running', [
            completedSteps[0],
            {
                key: 'suppressions',
                label: 'Suppressed addresses',
                status: 'running',
                processed: 12000,
                imported: 11874,
                warnings: [],
                last_error: 'Customer.io returned HTTP 503.',
            },
            { ...completedSteps[2], status: 'pending', processed: 0, imported: 0 },
        ]),
    ],
}
ImportRunning.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr="customerio-import-run-progress"]',
    },
}

export const ImportFinished: StoryFn<StoryProps> = Template.bind({})
ImportFinished.args = {
    syncConfig: importedConfig,
    importRuns: [importRun('completed', completedSteps)],
    step: 'import',
}
ImportFinished.parameters = { testOptions: { waitForSelector: '[data-attr="customerio-import-run-progress"]' } }

export const ImportStepFailed: StoryFn<StoryProps> = Template.bind({})
ImportStepFailed.args = {
    syncConfig: importedConfig,
    importRuns: [
        importRun('failed', [
            completedSteps[1],
            {
                ...completedSteps[2],
                status: 'failed',
                processed: 1000,
                imported: 1000,
                last_error: 'Customer.io returned HTTP 503.',
            },
        ]),
    ],
    step: 'import',
}
ImportStepFailed.parameters = { testOptions: { waitForSelector: '[data-attr="customerio-import-run-progress"]' } }

export const KeepInSync: StoryFn<StoryProps> = Template.bind({})
KeepInSync.args = { syncConfig: importedConfig, step: 'sync' }
KeepInSync.parameters = wizardReady

export const KeepInSyncEnabled: StoryFn<StoryProps> = Template.bind({})
KeepInSyncEnabled.args = { syncConfig: syncEnabledConfig, step: 'sync' }
KeepInSyncEnabled.parameters = wizardReady
