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
            sync_type: 'incremental',
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
            // Kept deliberately: the endpoint answers for the whole warehouse, and this row must
            // not appear in the rendered scene.
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

// The synced-sources table is the real one from the sources page, so the stories have to answer
// the endpoints it loads for itself.
const SOURCES = {
    count: 2,
    results: [
        {
            id: '1',
            source_type: 'Stripe',
            prefix: null,
            status: 'Running',
            access_method: 'warehouse',
            last_run_at: '2026-09-25T08:00:00Z',
            schemas: [
                { id: 's1', name: 'charges', should_sync: true, status: 'Running' },
                { id: 's2', name: 'customers', should_sync: true, status: 'Completed' },
            ],
        },
        {
            id: '2',
            source_type: 'Postgres',
            prefix: 'billing_',
            status: 'Error',
            access_method: 'warehouse',
            last_run_at: '2026-09-24T02:00:00Z',
            schemas: [{ id: 's3', name: 'public.invoices', should_sync: true, status: 'Failed' }],
        },
    ],
}

// `loadAppMetricsTimeSeries` reads each row as [labels, breakdown, values], so the destination
// chart needs the raw HogQL shape rather than the parsed one.
const DAYS = ['2026-09-22', '2026-09-23', '2026-09-24', '2026-09-25', '2026-09-26', '2026-09-27', '2026-09-28']

// One request per destination now, each filtered on `instanceId`, so the mock answers a single
// unnamed series rather than a breakdown.
const ROWS_QUERY = {
    results: [[DAYS, 'rows_synced', [120000, 98000, 141000, 132000, 87000, 155000, 149000]]],
}

const DESTINATIONS = {
    count: 2,
    results: [
        { id: 'dest-1', name: 'PostHog warehouse', type: 'PostHogWarehouse' },
        { id: 'dest-2', name: 'Analytics Postgres', type: 'Postgres' },
    ],
}

function mocks(health: Record<string, unknown>, runs: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/data_warehouse/job_stats': JOB_STATS,
            '/api/projects/:team_id/data_warehouse/total_rows_stats': ROWS_STATS,
            '/api/projects/:team_id/data_warehouse/data_health_issues': health,
            '/api/projects/:team_id/data_warehouse/completed_activity': runs,
            '/api/projects/:team_id/external_data_sources': SOURCES,
            '/api/projects/:team_id/external_data_sources/wizard': {},
            '/api/projects/:team_id/external_data_destinations': DESTINATIONS,
        },
        post: {
            '/api/projects/:team_id/query/:query_kind/': ROWS_QUERY,
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
