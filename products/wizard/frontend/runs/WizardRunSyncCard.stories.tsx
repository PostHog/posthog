import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { WizardRunSyncCard } from './WizardRunSyncCard'
import { WizardRunSyncRunPicker } from './WizardRunSyncRunPicker'

const run: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/project' },
    program: {
        id: 'setup',
        name: 'PostHog setup',
        description: 'Set up analytics',
        wizard_version: '1.0.0',
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
    updated_at: '2026-09-23T10:01:00Z',
    started_at: '2026-09-23T10:00:30Z',
    finished_at: null,
    deadline_at: null,
}

const task = (name: string, status: WizardRunTaskApi['status']): WizardRunTaskApi => ({
    name,
    status,
    created_at: '2026-09-23T10:00:00Z',
    started_at: null,
    completed_at: null,
    failed_at: null,
    error_message: null,
})

const meta: Meta<typeof WizardRunSyncCard> = {
    title: 'Products/Wizard/Wizard run sync card',
    component: WizardRunSyncCard,
    parameters: { layout: 'fullscreen', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => (
            <div className="flex min-h-[640px] items-end justify-end bg-primary p-8">
                <Story />
            </div>
        ),
    ],
    args: {
        run,
        elapsedSeconds: 134,
        tasks: [
            task('Identify the existing analytics integration', 'completed'),
            task('Install the SDK and configure capture', 'running'),
            task('Verify events in PostHog', 'created'),
        ],
        onExpand: () => {},
        onExpandIcon: () => {},
        onClose: () => {},
        onHide: () => {},
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const Running: Story = {}

export const MultipleRuns: Story = {
    render: function MultipleRunCard(args) {
        const runs = [
            run,
            {
                ...run,
                id: '00000000-0000-4000-8000-000000000002',
                environment: 'local' as const,
                workspace: { type: 'local_folder' as const, project_name: 'example-project' },
                created_at: '2026-09-23T09:30:00Z',
            },
            {
                ...run,
                id: '00000000-0000-4000-8000-000000000003',
                status: 'completed' as const,
                stage: null,
                finished_at: '2026-09-23T09:05:00Z',
                workspace: { type: 'git_repository' as const, repository: 'example/other-project' },
                created_at: '2026-09-23T09:00:00Z',
            },
        ]
        const [selectedRun, setSelectedRun] = useState<WizardRunApi>(run)

        return (
            <WizardRunSyncCard
                {...args}
                run={selectedRun}
                tasks={selectedRun.id === run.id ? args.tasks : []}
                runPicker={
                    <WizardRunSyncRunPicker
                        runs={runs}
                        activeCount={2}
                        currentRunId={selectedRun.id}
                        onSelect={setSelectedRun}
                        onOpen={() => {}}
                    />
                }
            />
        )
    },
}

export const LocalRunning: Story = {
    args: {
        run: {
            ...run,
            environment: 'local',
            workspace: { type: 'local_folder', project_name: 'example-project' },
            stage: null,
        },
    },
}

export const Completed: Story = {
    args: {
        run: { ...run, status: 'completed', stage: null },
        tasks: [task('Install the SDK and configure capture', 'running')],
    },
}
