import { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator } from '~/mocks/browser'

import { PipelineOverviewScene } from './PipelineOverviewScene'

const HEALTHY = { results: [], count: 0 }

const UNHEALTHY = {
    count: 3,
    results: [
        {
            id: '1',
            name: 'charges',
            type: 'external_data_sync',
            source_type: 'Stripe',
            status: 'failed',
            error: 'Authentication error: expired API key',
            failed_at: '2026-09-21T04:15:00Z',
            url: '/data-management/sources/1',
        },
        {
            id: '2',
            name: 'public.invoices',
            type: 'external_data_sync',
            source_type: 'Postgres',
            status: 'billing_limit',
            error: 'Billing limit reached for this period',
            failed_at: '2026-09-24T02:00:00Z',
            url: '/data-management/sources/2',
        },
        {
            id: '3',
            name: 'account_activity',
            type: 'materialized_view',
            status: 'degraded',
            error: null,
            failed_at: '2026-09-25T09:00:00Z',
            url: '/data-warehouse/view/3',
        },
    ],
}

const JOB_STATS = {
    days: 7,
    cutoff_time: '2026-09-18T00:00:00Z',
    total_jobs: 412,
    successful_jobs: 401,
    failed_jobs: 11,
    external_data_jobs: { total: 380, running: 3, successful: 371, failed: 9 },
    modeling_jobs: { total: 32, running: 1, successful: 30, failed: 2 },
    breakdown: {},
}

const ROWS_STATS = {
    billing_available: true,
    billing_interval: 'month',
    billing_period_start: '2026-09-01T00:00:00Z',
    billing_period_end: '2026-10-01T00:00:00Z',
    total_rows: 48200000,
    tracked_billing_rows: 46000000,
    pending_billing_rows: 2200000,
    materialized_rows_in_billing_period: 1200000,
    breakdown_of_rows_by_source: {},
}

const FAILED_RUNS = {
    next: null,
    previous: null,
    results: [
        {
            id: 'run-1',
            type: 'Stripe',
            name: 'charges',
            status: 'Failed',
            rows: 0,
            created_at: '2026-09-25T08:00:00Z',
            finished_at: '2026-09-25T08:01:00Z',
            latest_error: 'Authentication error: expired API key',
            workflow_run_id: 'wf-1',
            origin: null,
        },
        {
            id: 'run-2',
            type: 'Salesforce',
            name: 'opportunity',
            status: 'Failed',
            rows: 0,
            created_at: '2026-09-25T05:40:00Z',
            finished_at: '2026-09-25T05:41:00Z',
            latest_error: 'Schema drift: column "forecast_category" changed type text to numeric',
            workflow_run_id: 'wf-2',
            origin: null,
        },
    ],
}

function mocks(health: Record<string, unknown>, runs: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/data_warehouse/job_stats': JOB_STATS,
            '/api/projects/:team_id/data_warehouse/total_rows_stats': ROWS_STATS,
            '/api/projects/:team_id/data_warehouse/data_health_issues': health,
            '/api/projects/:team_id/data_warehouse/completed_activity': runs,
        },
    })
}

const meta: Meta<typeof PipelineOverviewScene> = {
    title: 'Scenes-App/ETL',
    component: PipelineOverviewScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        // The scene refuses to render without this, so every story has to carry it.
        featureFlags: [FEATURE_FLAGS.WAREHOUSE_MULTI_DESTINATION],
    },
}
export default meta

const Template: StoryFn = () => <PipelineOverviewScene />

export const NeedsAttention = Template.bind({})
NeedsAttention.decorators = [mocks(UNHEALTHY, FAILED_RUNS)]

export const Healthy = Template.bind({})
Healthy.decorators = [mocks(HEALTHY, { results: [], next: null, previous: null })]
