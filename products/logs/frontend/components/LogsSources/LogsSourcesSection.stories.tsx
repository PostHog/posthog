import { Meta, StoryFn } from '@storybook/react'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import type {
    LogsSourceApi,
    LogsSourceHealthApi,
    LogsSourceSetupApi,
} from 'products/logs/frontend/generated/api.schemas'

import { logsSourcesLogic } from './logsSourcesLogic'
import { LogsSourcesSection } from './LogsSourcesSection'

const sources: LogsSourceApi[] = [
    {
        id: '6f1a2b3c-0000-4000-8000-000000000001',
        name: 'Production account',
        provider: 'aws_cloudwatch',
        mode: 'push',
        enabled: true,
        config: { region: 'us-east-1', default_labels: { env: 'prod' }, service_name_overrides: {} },
        created_by: 1,
        created_at: '2026-09-16T10:00:00Z',
        updated_at: null,
    },
    {
        id: '6f1a2b3c-0000-4000-8000-000000000002',
        name: 'Staging account',
        provider: 'aws_cloudwatch',
        mode: 'push',
        enabled: false,
        config: { region: 'eu-central-1', default_labels: {}, service_name_overrides: {} },
        created_by: 1,
        created_at: '2026-09-15T10:00:00Z',
        updated_at: null,
    },
]

const health: LogsSourceHealthApi = {
    status: 'receiving',
    last_received_at: '2026-09-16T11:58:00Z',
    records_received_24h: 128_402,
    records_dropped_24h: 0,
}

const setup: LogsSourceSetupApi = {
    endpoint_path: '/i/v1/logs/aws/firehose/6f1a2b3c-0000-4000-8000-000000000001',
    endpoint_url: 'https://us.i.posthog.com/i/v1/logs/aws/firehose/6f1a2b3c-0000-4000-8000-000000000001',
    access_key: 'phc_example_project_api_key',
    buffering_size_mb: 1,
    buffering_interval_seconds: 60,
    retry_duration_seconds: 300,
    content_encoding: 'GZIP',
    quick_create_url:
        'https://us-east-1.console.aws.amazon.com/cloudformation/home?region=us-east-1#/stacks/quickcreate?templateURL=https%3A%2F%2Ftemplates.example.com%2Ffirehose.yaml',
}

const meta: Meta = {
    title: 'Scenes-App/Logs/Settings/LogsSourcesSection',
    component: LogsSourcesSection,
    parameters: {
        layout: 'padded',
        featureFlags: [FEATURE_FLAGS.LOGS_CLOUD_SOURCES],
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

export const WithSources: StoryFn = () => <LogsSourcesSection />
WithSources.decorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/logs/sources/': { count: sources.length, results: sources },
            '/api/projects/:team_id/logs/sources/health/': {
                sources: Object.fromEntries(sources.map((source) => [source.id, health])),
            },
            '/api/projects/:team_id/logs/sources/:id/setup/': setup,
        },
    }),
]

export const WizardConnectStep: StoryFn = () => {
    useEffect(() => {
        const unmount = logsSourcesLogic.mount()
        logsSourcesLogic.actions.openWizardForSource(sources[0].id)
        return unmount
    }, [])
    return <LogsSourcesSection />
}
WizardConnectStep.decorators = WithSources.decorators

export const Empty: StoryFn = () => <LogsSourcesSection />
Empty.decorators = [
    mswDecorator({
        get: {
            '/api/projects/:team_id/logs/sources/': { count: 0, results: [] },
        },
    }),
]
