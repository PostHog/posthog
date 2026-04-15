import { Meta, StoryFn } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import { customerIOImportLogic } from './customerIOImportLogic'
import type { OptOutSyncConfigResponse } from './customerIOImportLogic'
import { CustomerIOImportModal } from './CustomerIOImportModal'

const syncConfigEndpoint = '/api/environments/:team_id/messaging_categories/optout_sync_config/'

function mockSyncConfig(config: OptOutSyncConfigResponse): Record<string, any> {
    return {
        get: {
            [syncConfigEndpoint]: config,
        },
    }
}

const emptySyncConfig: OptOutSyncConfigResponse = {
    app_integration_id: null,
    app_import_result: null,
    csv_import_result: null,
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
}

const Template: StoryFn<StoryProps> = ({ syncConfig }) => {
    useStorybookMocks(mockSyncConfig(syncConfig))
    const { openImportModal } = useActions(customerIOImportLogic)

    useEffect(() => {
        openImportModal()
    }, [])

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
