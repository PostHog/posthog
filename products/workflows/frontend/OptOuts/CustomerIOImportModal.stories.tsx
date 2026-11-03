import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import type { ProviderImportRunApi } from 'products/messaging/frontend/generated/api.schemas'

import { customerIOImportLogic } from './customerIOImportLogic'
import type { OptOutSyncConfigResponse } from './customerIOImportLogic'
import { CustomerIOImportModal } from './CustomerIOImportModal'

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

const step1FailedConfig: OptOutSyncConfigResponse = {
    ...emptySyncConfig,
    app_import_result: {
        status: 'failed',
        imported_at: '2026-04-13T10:00:00Z',
        error: 'Invalid API key. Please check your credentials and try again.',
    },
}

const step1CompletedConfig: OptOutSyncConfigResponse = {
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

const bothStepsCompletedConfig: OptOutSyncConfigResponse = {
    ...step1CompletedConfig,
    csv_import_result: {
        status: 'completed',
        imported_at: '2026-04-13T11:00:00Z',
        total_rows: 5000,
        users_with_optouts: 3200,
        users_skipped: 1800,
        parse_errors: 3,
    },
}

const step2FailedConfig: OptOutSyncConfigResponse = {
    ...step1CompletedConfig,
    csv_import_result: {
        status: 'failed',
        imported_at: '2026-04-13T11:00:00Z',
        error: 'No categories found. Please run API import first.',
    },
}

const meta: Meta = {
    title: 'Products/Workflows/CustomerIOImportModal',
    component: CustomerIOImportModal,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type StoryProps = {
    syncConfig: OptOutSyncConfigResponse
    importRuns?: ProviderImportRunApi[]
}

const Template: StoryFn<StoryProps> = ({ syncConfig, importRuns }) => {
    useStorybookMocks(mockSyncConfig(syncConfig, importRuns))
    const { openImportModal } = useActions(customerIOImportLogic)

    useEffect(() => {
        openImportModal()
    }, [openImportModal])

    return <CustomerIOImportModal />
}

export const BothStepsNotCompleted: StoryFn<StoryProps> = Template.bind({})
BothStepsNotCompleted.args = { syncConfig: emptySyncConfig }
BothStepsNotCompleted.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step1FailedInvalidKey: StoryFn<StoryProps> = Template.bind({})
Step1FailedInvalidKey.args = { syncConfig: step1FailedConfig }
Step1FailedInvalidKey.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step1Completed: StoryFn<StoryProps> = Template.bind({})
Step1Completed.args = { syncConfig: step1CompletedConfig }
Step1Completed.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step1CompletedButKeyDeleted: StoryFn<StoryProps> = Template.bind({})
Step1CompletedButKeyDeleted.args = {
    syncConfig: {
        ...step1CompletedConfig,
        app_integration_id: null,
    },
}
Step1CompletedButKeyDeleted.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const BothStepsCompleted: StoryFn<StoryProps> = Template.bind({})
BothStepsCompleted.args = { syncConfig: bothStepsCompletedConfig }
BothStepsCompleted.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step2Failed: StoryFn<StoryProps> = Template.bind({})
Step2Failed.args = { syncConfig: step2FailedConfig }
Step2Failed.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

const allStepsCompletedConfig: OptOutSyncConfigResponse = {
    ...bothStepsCompletedConfig,
    webhook_enabled: true,
    has_webhook_secret: true,
}

const webhookDisabledConfig: OptOutSyncConfigResponse = {
    ...bothStepsCompletedConfig,
    webhook_enabled: false,
    has_webhook_secret: true,
}

export const Step3WebhookNotConfigured: StoryFn<StoryProps> = Template.bind({})
Step3WebhookNotConfigured.args = { syncConfig: bothStepsCompletedConfig }
Step3WebhookNotConfigured.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step3WebhookEnabled: StoryFn<StoryProps> = Template.bind({})
Step3WebhookEnabled.args = { syncConfig: allStepsCompletedConfig }
Step3WebhookEnabled.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step3WebhookDisabled: StoryFn<StoryProps> = Template.bind({})
Step3WebhookDisabled.args = { syncConfig: webhookDisabledConfig }
Step3WebhookDisabled.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

const step4NotConfiguredConfig: OptOutSyncConfigResponse = {
    ...allStepsCompletedConfig,
    track_enabled: false,
    has_track_credentials: false,
}

const step4EnabledConfig: OptOutSyncConfigResponse = {
    ...allStepsCompletedConfig,
    track_enabled: true,
    has_track_credentials: true,
}

const step4DisabledConfig: OptOutSyncConfigResponse = {
    ...allStepsCompletedConfig,
    track_enabled: false,
    has_track_credentials: true,
}

export const Step4TrackNotConfigured: StoryFn<StoryProps> = Template.bind({})
Step4TrackNotConfigured.args = { syncConfig: step4NotConfiguredConfig }
Step4TrackNotConfigured.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step4TrackEnabled: StoryFn<StoryProps> = Template.bind({})
Step4TrackEnabled.args = { syncConfig: step4EnabledConfig }
Step4TrackEnabled.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const Step4TrackDisabled: StoryFn<StoryProps> = Template.bind({})
Step4TrackDisabled.args = { syncConfig: step4DisabledConfig }
Step4TrackDisabled.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

export const AllStepsCompleted: StoryFn<StoryProps> = Template.bind({})
AllStepsCompleted.args = { syncConfig: step4EnabledConfig }
AllStepsCompleted.parameters = { testOptions: { waitForSelector: '.LemonCollapse' } }

const storedKeyConfig: OptOutSyncConfigResponse = { ...emptySyncConfig, app_integration_id: 1 }

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

export const ImportRunning: StoryFn<StoryProps> = Template.bind({})
ImportRunning.args = {
    syncConfig: storedKeyConfig,
    importRuns: [
        importRun('running', [
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
                status: 'running',
                processed: 12000,
                imported: 11874,
                warnings: [],
                last_error: 'Customer.io returned HTTP 503.',
            },
            {
                key: 'opt_outs',
                label: 'Global unsubscribes',
                status: 'pending',
                processed: 0,
                imported: 0,
                warnings: [],
                last_error: null,
            },
        ]),
    ],
}
ImportRunning.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '[data-attr="customerio-import-run-progress"]',
    },
}

export const ImportStepFailed: StoryFn<StoryProps> = Template.bind({})
ImportStepFailed.args = {
    syncConfig: storedKeyConfig,
    importRuns: [
        importRun('failed', [
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
                status: 'failed',
                processed: 1000,
                imported: 1000,
                warnings: [],
                last_error: 'Customer.io returned HTTP 503.',
            },
        ]),
    ],
}
ImportStepFailed.parameters = {
    mockDate: '2026-04-13 10:30:00',
    testOptions: { waitForSelector: '[data-attr="customerio-import-run-progress"]' },
}
