import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type {
    ModelCatalogueResponseApi,
    TaskAnalysisRunApi,
    TaskRunAnalysisActivityRequestApi,
    TasksAnalysisConfigResponseApi,
} from './generated/api.schemas'

const CATALOGUE: ModelCatalogueResponseApi = {
    models: [
        {
            runtime_adapter: 'claude',
            model: 'claude-opus-4-8',
            display_name: 'Claude Opus 4.8',
            supported_efforts: ['low', 'medium', 'high'],
        },
        {
            runtime_adapter: 'claude',
            model: 'claude-sonnet-4-6',
            display_name: 'Claude Sonnet 4.6',
            supported_efforts: ['low', 'medium', 'high'],
        },
        {
            runtime_adapter: 'codex',
            model: 'gpt-5.3-codex',
            display_name: 'GPT-5.3 Codex',
            supported_efforts: ['low', 'medium', 'high', 'xhigh'],
        },
    ],
}

const CONFIG: TasksAnalysisConfigResponseApi = {
    analysis_run_preferences: { runtime_adapter: 'claude', model: 'claude-opus-4-8', reasoning_effort: 'medium' },
}

function activity(overrides: Partial<TaskRunAnalysisActivityRequestApi>): TaskRunAnalysisActivityRequestApi {
    return {
        goal_kind: 'produce',
        goal: 'Add the export button to the dashboard header',
        outcome: 'worked',
        evidence: 'Edited DashboardHeader.tsx and ran the scene test.',
        start_line: 1,
        end_line: 40,
        tool_calls: 12,
        failed_calls: 0,
        seconds: 240,
        idle_seconds: 0,
        ...overrides,
    }
}

function run(overrides: Partial<TaskAnalysisRunApi>): TaskAnalysisRunApi {
    return {
        id: '11111111-1111-4111-8111-111111111111',
        task_id: '22222222-2222-4222-8222-222222222222',
        status: 'completed',
        created_at: '2026-09-07T09:15:00Z',
        completed_at: '2026-09-07T09:21:00Z',
        error_message: null,
        runtime_adapter: 'claude',
        model: 'claude-opus-4-8',
        reasoning_effort: 'medium',
        target_task_id: '33333333-3333-4333-8333-333333333333',
        target_run_id: '44444444-4444-4444-8444-444444444444',
        target_repository: 'example-org/example-repo',
        activities: [],
        ...overrides,
    }
}

const RUNS: TaskAnalysisRunApi[] = [
    run({
        id: 'aaaaaaaa-0000-4000-8000-000000000001',
        status: 'in_progress',
        created_at: '2026-09-07T22:02:00Z',
        completed_at: null,
    }),
    run({
        id: 'aaaaaaaa-0000-4000-8000-000000000002',
        activities: [
            activity({}),
            activity({
                goal_kind: 'verify',
                goal: 'Run the dashboard tests',
                outcome: 'failed',
                blocker_kind: 'service_down',
                blocker_name: 'postgres',
                repair: 'Started the database container and reran the tests.',
                start_line: 41,
                end_line: 90,
                tool_calls: 6,
                failed_calls: 2,
                seconds: 180,
                idle_seconds: 30,
            }),
        ],
    }),
    run({
        id: 'aaaaaaaa-0000-4000-8000-000000000003',
        status: 'failed',
        created_at: '2026-09-06T17:40:00Z',
        completed_at: '2026-09-06T17:41:00Z',
        error_message: 'The sandbox stopped before the analysis finished.',
        model: null,
        reasoning_effort: null,
        runtime_adapter: null,
        target_repository: null,
    }),
]

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Tasks/Task analysis',
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/tasks/models/': () => [200, CATALOGUE] } })],
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/tasks/analysis/config/': () => [200, CONFIG],
                    '/api/projects/:team_id/tasks/analysis/runs/': () => [
                        200,
                        { count: RUNS.length, next: null, previous: null, results: RUNS },
                    ],
                },
            },
        },
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-09-08',
        pageUrl: urls.taskAnalysisRuns(),
        featureFlags: { [FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS]: true },
        testOptions: { waitForLoadersToDisappear: true },
    },
}
export default meta

type Story = StoryObj<{}>

export const WithRuns: Story = {}

export const SettingsTab: Story = {
    parameters: {
        pageUrl: urls.taskAnalysisSettings(),
    },
}

export const NoRuns: Story = {
    parameters: {
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/tasks/analysis/config/': () => [200, { analysis_run_preferences: {} }],
                    '/api/projects/:team_id/tasks/analysis/runs/': () => [
                        200,
                        { count: 0, next: null, previous: null, results: [] },
                    ],
                },
            },
        },
    },
}

export const FlagOff: Story = {
    parameters: {
        featureFlags: { [FEATURE_FLAGS.POSTHOG_CODE_TASK_ANALYSIS]: false },
    },
}
