import { Meta, StoryObj } from '@storybook/react'
import { delay, HttpResponse } from 'msw'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from './types'

const taskTrackerUrl = (): string => '/tasks'
const taskNewUrl = (): string => '/tasks/new'
const taskDetailUrl = (taskId: string): string => `/tasks/${taskId}`

const CREATED_BY: Task['created_by'] = {
    id: 1,
    uuid: '01234567-89ab-cdef-0123-456789abcdef',
    distinct_id: 'user-distinct-id',
    first_name: 'Lottie',
    email: 'lottie@posthog.com',
}

function mockRun(taskId: string, status: TaskRunStatus, createdAt: string, completedAt: string | null): TaskRun {
    return {
        id: `run-${taskId}`,
        task: taskId,
        stage: null,
        branch: status === TaskRunStatus.COMPLETED ? 'posthog/task-branch' : null,
        status,
        environment: TaskRunEnvironment.CLOUD,
        log_url: null,
        error_message: null,
        output: null,
        state: {},
        artifacts: [],
        created_at: createdAt,
        updated_at: completedAt ?? createdAt,
        completed_at: completedAt,
    }
}

const TASKS: Task[] = [
    {
        id: 'task-1',
        task_number: 1,
        slug: 'TASK-1',
        title: 'Add retention graph export',
        description: 'Let users download the retention graph as a CSV from the insight menu.',
        origin_product: OriginProduct.USER_CREATED,
        repository: 'PostHog/posthog',
        github_integration: 1,
        json_schema: null,
        internal: false,
        latest_run: mockRun('task-1', TaskRunStatus.COMPLETED, '2024-01-15T09:30:00Z', '2024-01-15T09:48:00Z'),
        created_at: '2024-01-15T09:25:00Z',
        updated_at: '2024-01-15T09:48:00Z',
        created_by: CREATED_BY,
    },
    {
        id: 'task-2',
        task_number: 2,
        slug: 'TASK-2',
        title: 'Fix cohort empty state in query builder',
        description: 'Handle an empty cohort gracefully instead of throwing in the query builder.',
        origin_product: OriginProduct.USER_CREATED,
        repository: 'PostHog/posthog',
        github_integration: 1,
        json_schema: null,
        internal: false,
        latest_run: mockRun('task-2', TaskRunStatus.IN_PROGRESS, '2024-01-15T11:40:00Z', null),
        created_at: '2024-01-15T11:38:00Z',
        updated_at: '2024-01-15T11:40:00Z',
        created_by: CREATED_BY,
    },
    {
        id: 'task-3',
        task_number: 3,
        slug: 'TASK-3',
        title: 'Investigate slow dashboard load',
        description: 'Profile the dashboard scene and find the slowest tiles on first paint.',
        origin_product: OriginProduct.USER_CREATED,
        repository: 'PostHog/posthog',
        github_integration: 1,
        json_schema: null,
        internal: false,
        latest_run: null,
        created_at: '2024-01-14T16:10:00Z',
        updated_at: '2024-01-14T16:10:00Z',
        created_by: CREATED_BY,
    },
]

const listResponse = (results: Task[]): Record<string, unknown> => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Tasks',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': listResponse(TASKS),
                '/api/projects/:team_id/tasks/repositories/': { repositories: ['PostHog/posthog'] },
                // Exact ids (not `:id`) so they never shadow the `repositories` action route.
                '/api/projects/:team_id/tasks/task-3/': TASKS[2],
                '/api/projects/:team_id/tasks/task-3/runs/': { count: 0, next: null, previous: null, results: [] },
                '/api/environments/:team_id/integrations/': { results: [] },
            },
        }),
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-01-15T12:00:00',
        featureFlags: [FEATURE_FLAGS.TASKS],
        pageUrl: taskTrackerUrl(),
    },
}
export default meta

type Story = StoryObj<typeof meta>

// Two-column layout: list on the left, the new-task composer on the right.
export const ListWithComposer: Story = {}

// New-task route — same two columns, composer is the focused right pane.
export const NewTask: Story = {
    parameters: {
        pageUrl: taskNewUrl(),
    },
}

// A task is selected: the row is highlighted and its detail fills the right column.
export const TaskSelected: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-3'),
    },
}

// The tasks request never resolves, so the list column shows its loading skeletons.
export const Loading: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': async () => {
                    await delay('infinite')
                    return HttpResponse.json(listResponse([]))
                },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/environments/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}

// No tasks yet — the list shows its empty state alongside the composer.
export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': listResponse([]),
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/environments/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}

// Below `lg` (1024px) the scene collapses to a single column; 568px lands in the mobile branch.
const MOBILE_VIEWPORT = { width: 568, height: 812 }
const MOBILE_PARAMETERS = {
    viewport: {
        defaultViewport: 'mobile2',
    },
    testOptions: { viewport: MOBILE_VIEWPORT },
}

// Mobile: the list fills the screen and scrolls with the page, with a floating "New task" button.
export const MobileList: Story = {
    parameters: MOBILE_PARAMETERS,
}

// Mobile: the new-task composer is the single full-screen column.
export const MobileNewTask: Story = {
    parameters: {
        ...MOBILE_PARAMETERS,
        pageUrl: taskNewUrl(),
    },
}

// Mobile: a selected task's detail fills the screen (its back button returns to the list).
export const MobileTaskSelected: Story = {
    parameters: {
        ...MOBILE_PARAMETERS,
        pageUrl: taskDetailUrl('task-3'),
    },
}
