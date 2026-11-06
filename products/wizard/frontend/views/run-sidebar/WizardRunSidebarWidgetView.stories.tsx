import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { WizardRunApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WizardRunSidebarWidgetView } from './WizardRunSidebarWidgetView'

const baseRun: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/project' },
    program: {
        id: 'posthog-integration',
        name: 'PostHog integration',
        description: 'Set up PostHog',
        wizard_version: '2.78.0',
        command: [],
        tags: [],
        required_programs: [],
        supported_environments: ['cloud'],
    },
    status: 'running',
    stage: 'executing_wizard',
    error_code: null,
    error_message: null,
    created_at: '2026-09-23T10:00:00Z',
    updated_at: '2026-09-23T10:02:00Z',
    started_at: '2026-09-23T10:00:30Z',
    finished_at: null,
    deadline_at: null,
}

const localRun: WizardRunApi = {
    ...baseRun,
    id: '00000000-0000-4000-8000-000000000002',
    environment: 'local',
    workspace: { type: 'local_folder', project_name: 'example-project' },
    created_at: '2026-09-23T09:58:00Z',
    started_at: '2026-09-23T09:58:00Z',
}

const addingEventsTask: WizardRunTaskApi = {
    name: 'Adding events to the project',
    status: 'running',
    created_at: '2026-09-23T10:01:00Z',
    started_at: '2026-09-23T10:01:00Z',
    completed_at: null,
    failed_at: null,
    error_message: null,
}

const meta: Meta<typeof WizardRunSidebarWidgetView> = {
    title: 'Products/Wizard/Wizard run sidebar widget',
    component: WizardRunSidebarWidgetView,
    render: function Render(args): JSX.Element {
        const [dismissed, setDismissed] = useState<string[]>([])
        return (
            <WizardRunSidebarWidgetView
                {...args}
                runs={args.runs.filter((run) => !dismissed.includes(run.id))}
                onDismissRuns={(ids) => {
                    args.onDismissRuns(ids)
                    setDismissed((current) => [...current, ...ids])
                }}
            />
        )
    },
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => (
            <div className="flex min-h-[420px] w-[560px] bg-surface-secondary p-4">
                <div className="w-60">
                    <Story />
                </div>
            </div>
        ),
    ],
    argTypes: {
        runs: { control: 'object' },
        tasksByRunId: { control: 'object' },
        initialHovered: { control: 'boolean' },
        initialMenuOpen: { control: 'boolean' },
    },
    args: {
        runs: [baseRun],
        tasksByRunId: { [baseRun.id]: [addingEventsTask] },
        onDismissRuns: () => {},
        initialHovered: false,
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const RunningTask: Story = {}

export const RunningTaskHovered: Story = {
    args: {
        initialHovered: true,
    },
}

export const RunningStage: Story = {
    args: {
        tasksByRunId: {},
    },
}

export const Starting: Story = {
    args: {
        runs: [{ ...baseRun, status: 'created', stage: 'dispatching', started_at: null }],
        tasksByRunId: {},
    },
}

export const LocalRun: Story = {
    args: {
        runs: [localRun],
        tasksByRunId: { [localRun.id]: [addingEventsTask] },
    },
}

export const MultipleRuns: Story = {
    args: {
        runs: [baseRun, localRun],
        tasksByRunId: {
            [baseRun.id]: [addingEventsTask],
            [localRun.id]: [],
        },
    },
}

export const MultipleRunsHovered: Story = {
    args: {
        ...MultipleRuns.args,
        initialHovered: true,
    },
}

export const MultipleRunsMenuOpen: Story = {
    args: {
        ...MultipleRuns.args,
        initialMenuOpen: true,
    },
}

export const Completed: Story = {
    args: { runs: [{ ...baseRun, status: 'completed', finished_at: '2026-09-23T10:03:00Z' }] },
}

export const Failed: Story = {
    args: {
        runs: [
            {
                ...baseRun,
                status: 'failed',
                error_message: 'The setup agent stopped.',
                finished_at: '2026-09-23T10:03:00Z',
            },
        ],
    },
}

export const MixedStatuses: Story = {
    args: {
        runs: [
            baseRun,
            { ...localRun, status: 'completed', finished_at: '2026-09-23T10:03:00Z' },
            {
                ...baseRun,
                id: 'audit-run',
                program: { ...baseRun.program, id: 'analytics-audit', name: 'Analytics audit' },
                status: 'failed',
                finished_at: '2026-09-23T10:03:00Z',
                error_message: 'The audit stopped.',
            },
        ],
        initialMenuOpen: true,
    },
}

export const ManyRuns: Story = {
    args: {
        runs: Array.from({ length: 36 }, (_, index) => ({
            ...baseRun,
            id: `example-run-${index}`,
            program: { ...baseRun.program, name: index % 2 ? 'Analytics audit' : 'PostHog integration' },
            status: (['running', 'failed', 'completed'] as const)[index % 3],
        })),
        initialMenuOpen: true,
    },
}

export const LongTaskName: Story = {
    args: {
        tasksByRunId: {
            [baseRun.id]: [
                {
                    ...addingEventsTask,
                    name: 'Installing the SDK and configuring autocapture across every page',
                },
            ],
        },
    },
}

export const Empty: Story = {
    args: {
        runs: [],
        tasksByRunId: {},
    },
}
