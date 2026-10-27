import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { delay, HttpResponse } from 'msw'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { urls } from 'scenes/urls'

import { panelLayoutLogic } from '~/layout/panel-layout/panelLayoutLogic'
import { mswDecorator } from '~/mocks/browser'

import { TaskRuntimeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { OriginProduct, Task, TaskRun, TaskRunEnvironment, TaskRunStatus } from '../../types/taskTypes'

const taskTrackerUrl = (): string => '/tasks'
const taskNewUrl = (): string => '/tasks/new'
const taskDetailUrl = (taskId: string): string => `/tasks/${taskId}`
const taskDetailRunUrl = (taskId: string, runId: string): string => `/tasks/${taskId}?runId=${runId}`

const CREATED_BY: Task['created_by'] = {
    id: 1,
    uuid: '01234567-89ab-cdef-0123-456789abcdef',
    distinct_id: 'user-distinct-id',
    first_name: 'Lottie',
    email: 'lottie@posthog.com',
}

function mockRun(
    taskId: string,
    status: TaskRunStatus,
    createdAt: string,
    completedAt: string | null,
    environment: TaskRunEnvironment = TaskRunEnvironment.CLOUD
): TaskRun {
    return {
        id: `run-${taskId}`,
        task: taskId,
        stage: null,
        branch: status === TaskRunStatus.COMPLETED ? 'posthog/task-branch' : null,
        status,
        environment,
        runtime_adapter: null,
        model: null,
        reasoning_effort: null,
        log_url: null,
        error_message: null,
        output: null,
        task_summary: null,
        task_tags: [],
        state: {},
        artifacts: [],
        created_at: createdAt,
        updated_at: completedAt ?? createdAt,
        completed_at: completedAt,
    }
}

const TASK_1_RUN = mockRun('task-1', TaskRunStatus.COMPLETED, '2024-01-15T09:30:00Z', '2024-01-15T09:48:00Z')

const TASKS: Task[] = [
    {
        id: 'task-1',
        task_number: 1,
        slug: 'TASK-1',
        title: 'Add retention graph export',
        description: 'Let users download the retention graph as a CSV from the insight menu.',
        origin_product: OriginProduct.USER_CREATED,
        runtime: TaskRuntimeEnumApi.Acp,
        repository: 'PostHog/posthog',
        github_integration: 1,
        signal_report: null,
        json_schema: null,
        internal: false,
        latest_run: TASK_1_RUN,
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
        runtime: TaskRuntimeEnumApi.Acp,
        repository: 'PostHog/posthog',
        github_integration: 1,
        signal_report: null,
        json_schema: null,
        internal: false,
        latest_run: mockRun(
            'task-2',
            TaskRunStatus.COMPLETED,
            '2024-01-15T11:40:00Z',
            '2024-01-15T11:52:00Z',
            TaskRunEnvironment.LOCAL
        ),
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
        runtime: TaskRuntimeEnumApi.Acp,
        repository: 'PostHog/posthog',
        github_integration: 1,
        signal_report: null,
        json_schema: null,
        internal: false,
        latest_run: null,
        created_at: '2024-01-14T16:10:00Z',
        updated_at: '2024-01-14T16:10:00Z',
        created_by: CREATED_BY,
    },
]

const PI_TASK_RUN = mockRun('task-4', TaskRunStatus.COMPLETED, '2024-01-15T10:05:00Z', '2024-01-15T10:12:00Z')

const PI_TASK: Task = {
    id: 'task-4',
    task_number: 4,
    slug: 'TASK-4',
    title: 'Rename the export button label',
    description: 'Change the export button label to sentence case.',
    origin_product: OriginProduct.USER_CREATED,
    runtime: TaskRuntimeEnumApi.Pi,
    repository: 'PostHog/posthog',
    github_integration: 1,
    signal_report: null,
    json_schema: null,
    internal: false,
    latest_run: PI_TASK_RUN,
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:12:00Z',
    created_by: CREATED_BY,
}

const piLogEntry = (eventId: string, event: Record<string, unknown>): Record<string, unknown> => ({
    type: 'pi_event',
    timestamp: '2024-01-15T10:06:00Z',
    event_id: `pi-boot-${eventId}`,
    event,
})

const PI_TASK_LOG = [
    { type: 'pi_run_started', timestamp: '2024-01-15T10:05:30Z', taskId: 'task-4', runId: 'run-task-4' },
    piLogEntry('1', {
        type: 'user_message',
        id: 'pi-user-1',
        timestamp: 1,
        content: [{ type: 'text', text: 'Change the export button label to sentence case.' }],
    }),
    piLogEntry('2', {
        type: 'assistant_thought_chunk',
        timestamp: 2,
        content: { type: 'text', text: 'Find the button label first.' },
    }),
    piLogEntry('3', {
        type: 'tool_call_started',
        timestamp: 3,
        toolCall: {
            id: 'pi-tool-read',
            name: 'read',
            title: 'read',
            kind: 'read',
            status: 'pending',
            rawInput: { path: 'frontend/src/scenes/insights/ExportButton.tsx' },
            locations: [{ path: 'frontend/src/scenes/insights/ExportButton.tsx' }],
        },
    }),
    piLogEntry('4', { type: 'tool_call_updated', timestamp: 4, toolCall: { id: 'pi-tool-read', status: 'completed' } }),
    piLogEntry('5', {
        type: 'tool_call_started',
        timestamp: 5,
        toolCall: {
            id: 'pi-tool-edit',
            name: 'edit',
            title: 'edit',
            kind: 'edit',
            status: 'pending',
            rawInput: { path: 'frontend/src/scenes/insights/ExportButton.tsx' },
        },
    }),
    piLogEntry('6', {
        type: 'tool_call_updated',
        timestamp: 6,
        toolCall: {
            id: 'pi-tool-edit',
            status: 'completed',
            content: [
                {
                    type: 'diff',
                    path: 'frontend/src/scenes/insights/ExportButton.tsx',
                    oldText: '<LemonButton>Export As CSV</LemonButton>',
                    newText: '<LemonButton>Export as CSV</LemonButton>',
                },
            ],
        },
    }),
    piLogEntry('7', {
        type: 'tool_call_started',
        timestamp: 7,
        toolCall: {
            id: 'pi-tool-bash',
            name: 'bash',
            title: 'bash',
            kind: 'execute',
            status: 'pending',
            rawInput: { command: 'pnpm --filter=@posthog/frontend format' },
        },
    }),
    piLogEntry('8', { type: 'tool_call_updated', timestamp: 8, toolCall: { id: 'pi-tool-bash', status: 'completed' } }),
    piLogEntry('9', {
        type: 'assistant_message_chunk',
        timestamp: 9,
        content: { type: 'text', text: 'The export button now reads "Export as CSV".' },
    }),
    piLogEntry('10', { type: 'turn_completed', timestamp: 10, stopReason: 'end_turn' }),
]

const listResponse = (results: Task[]): Record<string, unknown> => ({
    count: results.length,
    next: null,
    previous: null,
    results,
})

const GITHUB_INTEGRATION = {
    id: 1,
    kind: 'github',
    display_name: 'PostHog',
    icon_url: '',
    config: {},
    created_by: null,
    created_at: '2024-01-01T00:00:00Z',
}

const CONVERSATIONS = {
    count: 2,
    next: null,
    previous: null,
    results: [
        {
            id: 'conversation-1',
            status: 'idle',
            title: 'Summarize weekly signups',
            created_at: '2024-01-15T10:00:00Z',
            updated_at: '2024-01-15T10:15:00Z',
            user: CREATED_BY,
        },
        {
            id: 'conversation-2',
            status: 'idle',
            title: 'Compare conversion by channel',
            created_at: '2024-01-14T14:00:00Z',
            updated_at: '2024-01-14T14:20:00Z',
            user: CREATED_BY,
        },
    ],
}

function UnifiedNavigationStory({ viewMode = 'new' }: { viewMode?: 'new' | 'legacy' }): JSX.Element {
    const { setNavExperimentTab } = useActions(panelLayoutLogic)
    const { setPhaiViewMode } = useActions(maxGlobalLogic)

    useEffect(() => {
        setNavExperimentTab('chat')
        setPhaiViewMode(viewMode)
    }, [setNavExperimentTab, setPhaiViewMode, viewMode])

    return <App />
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Tasks',
    decorators: [
        mswDecorator({
            get: {
                '/api/code/invites/check-access/': { has_access: true, has_loops_access: false },
                '/api/projects/:team_id/tasks/': listResponse(TASKS),
                '/api/projects/:team_id/tasks/repositories/': { repositories: ['PostHog/posthog'] },
                // nosemgrep: no-environments-api-urls-frontend -- Storybook mock for the shared AI navigation.
                '/api/environments/:team_id/conversations/': CONVERSATIONS,
                // Exact ids (not `:id`) so they never shadow the `repositories` action route.
                '/api/projects/:team_id/tasks/task-3/': TASKS[2],
                '/api/projects/:team_id/tasks/task-3/runs/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
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

export const Composer: Story = {}

export const UnifiedNavigation: Story = {
    render: () => <UnifiedNavigationStory />,
    parameters: {
        featureFlags: [FEATURE_FLAGS.TASKS, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
        pageUrl: urls.ai(),
    },
}

export const AiTaskSelected: Story = {
    render: () => <UnifiedNavigationStory viewMode="legacy" />,
    parameters: {
        pageUrl: urls.aiTask('task-3'),
    },
}

export const CloudTaskSelected: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-1'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-1/': TASKS[0],
                '/api/projects/:team_id/tasks/task-1/runs/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [TASK_1_RUN],
                },
                '/api/projects/:team_id/tasks/task-1/runs/run-task-1/': TASK_1_RUN,
                '/api/projects/:team_id/tasks/task-1/runs/run-task-1/logs': () =>
                    new HttpResponse(
                        JSON.stringify({
                            type: 'notification',
                            notification: {
                                method: 'session/update',
                                params: {
                                    update: {
                                        sessionUpdate: 'agent_message',
                                        messageId: 'task-1-msg',
                                        content: {
                                            type: 'text',
                                            text: 'Added a CSV export to the retention graph insight menu.',
                                        },
                                    },
                                },
                            },
                        })
                    ),
            },
        }),
    ],
}

export const PiTaskSelected: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-4'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-4/': PI_TASK,
                '/api/projects/:team_id/tasks/task-4/runs/': {
                    count: 1,
                    next: null,
                    previous: null,
                    results: [PI_TASK_RUN],
                },
                '/api/projects/:team_id/tasks/task-4/runs/run-task-4/': PI_TASK_RUN,
                '/api/projects/:team_id/tasks/task-4/runs/run-task-4/logs': () =>
                    new HttpResponse(PI_TASK_LOG.map((entry) => JSON.stringify(entry)).join('\n')),
            },
        }),
    ],
}

export const NewTask: Story = {
    parameters: {
        pageUrl: taskNewUrl(),
    },
}

export const NewTaskQuill: Story = {
    parameters: {
        pageUrl: taskNewUrl(),
        featureFlags: [FEATURE_FLAGS.TASKS, FEATURE_FLAGS.PHAI_QUILL],
    },
}

// New-task route with a GitHub integration connected — the footer shows the repository picker chip (and,
// once a repo is auto/selected, the branch picker) instead of the "Connect GitHub" chip.
export const NewTaskWithRepository: Story = {
    parameters: {
        pageUrl: taskNewUrl(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/integrations/': { results: [GITHUB_INTEGRATION] },
                '/api/environments/:team_id/integrations/1/github_repos': {
                    repositories: [
                        { id: 1, name: 'posthog', full_name: 'PostHog/posthog' },
                        { id: 2, name: 'posthog.com', full_name: 'PostHog/posthog.com' },
                    ],
                    has_more: false,
                },
                '/api/environments/:team_id/integrations/1/github_branches': {
                    branches: ['master', 'release'],
                    default_branch: 'master',
                    has_more: false,
                },
            },
        }),
    ],
}

export const TaskSelected: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-3'),
    },
}

export const Loading: Story = {
    render: () => <UnifiedNavigationStory />,
    parameters: {
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': async () => {
                    await delay('infinite')
                    return HttpResponse.json(listResponse([]))
                },
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}

export const ListLoadError: Story = {
    render: () => <UnifiedNavigationStory />,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': () =>
                    HttpResponse.json({ detail: 'Could not load tasks.' }, { status: 500 }),
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
            },
        }),
    ],
}

// Detail route before either the task payload or run list has resolved.
export const TaskDetailLoading: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-1'),
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-1/': async () => {
                    await delay('infinite')
                    return HttpResponse.json(TASKS[0])
                },
                '/api/projects/:team_id/tasks/task-1/runs/': async () => {
                    await delay('infinite')
                    return HttpResponse.json({ count: 0, next: null, previous: null, results: [] })
                },
            },
        }),
    ],
}

// Missing task id uses the shared NotFound scene convention.
export const TaskNotFound: Story = {
    parameters: {
        pageUrl: taskDetailUrl('missing-task'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/missing-task/': () =>
                    HttpResponse.json({ detail: 'Not found.' }, { status: 404 }),
                '/api/projects/:team_id/tasks/missing-task/runs/': () =>
                    HttpResponse.json({ detail: 'Not found.' }, { status: 404 }),
            },
        }),
    ],
}

// Non-404 task load failures render inline with a retry action.
export const TaskLoadError: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-1'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-1/': () =>
                    HttpResponse.json({ detail: 'Could not load task.' }, { status: 500 }),
                '/api/projects/:team_id/tasks/task-1/runs/': { count: 0, next: null, previous: null, results: [] },
            },
        }),
    ],
}

// Run-list failures are isolated from the already-loaded task metadata and description.
export const TaskRunsLoadError: Story = {
    parameters: {
        pageUrl: taskDetailUrl('task-1'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-1/': TASKS[0],
                '/api/projects/:team_id/tasks/task-1/runs/': () =>
                    HttpResponse.json({ detail: 'Could not load task runs.' }, { status: 500 }),
            },
        }),
    ],
}

// Deep-linked run ids that no longer exist use the same NotFound convention as missing tasks.
export const TaskRunNotFound: Story = {
    parameters: {
        pageUrl: taskDetailRunUrl('task-1', '00000000-0000-4000-8000-000000000001'),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/task-1/': TASKS[0],
                '/api/projects/:team_id/tasks/task-1/runs/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/tasks/task-1/runs/00000000-0000-4000-8000-000000000001/': () =>
                    HttpResponse.json({ detail: 'Not found.' }, { status: 404 }),
            },
        }),
    ],
}

export const Empty: Story = {
    render: () => <UnifiedNavigationStory />,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/tasks/': listResponse([]),
                '/api/projects/:team_id/tasks/repositories/': { repositories: [] },
                '/api/projects/:team_id/integrations/': { results: [] },
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

export const MobileComposer: Story = {
    parameters: MOBILE_PARAMETERS,
}

// Mobile: the new-task composer is the single full-screen column.
export const MobileNewTask: Story = {
    parameters: {
        ...MOBILE_PARAMETERS,
        pageUrl: taskNewUrl(),
    },
}

export const MobileTaskSelected: Story = {
    parameters: {
        ...MOBILE_PARAMETERS,
        pageUrl: taskDetailUrl('task-3'),
    },
}
