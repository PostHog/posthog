import type { Meta, StoryObj } from '@storybook/react'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WizardInstallSyncView } from './WizardInstallSyncView'

const NOW = new Date('2026-09-23T10:03:00Z').getTime()

const run: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'local',
    workspace: { type: 'local_folder', project_name: 'example-project' },
    program: {
        id: 'posthog-integration',
        name: 'PostHog integration',
        description: 'Set up PostHog',
        wizard_version: '2.78.0',
        command: [],
        tags: [],
        required_programs: [],
        supported_environments: ['local'],
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

const task = (name: string, status: WizardRunTaskApi['status']): WizardRunTaskApi => ({
    name,
    status,
    created_at: '2026-09-23T10:00:00Z',
    started_at: status === 'created' ? null : '2026-09-23T10:01:00Z',
    completed_at: status === 'completed' ? '2026-09-23T10:02:00Z' : null,
    failed_at: status === 'failed' ? '2026-09-23T10:02:00Z' : null,
    error_message: null,
})

const artifacts: WizardRunArtifactApi[] = [
    {
        id: 'artifact-pr',
        team_id: 1,
        run_id: run.id,
        artifact_type: 'pull_request',
        url: 'https://github.com/example/project/pull/12',
        number: 12,
        repository: 'example/project',
        head_branch: 'posthog/setup',
        base_branch: 'main',
        created_at: '2026-09-23T10:02:00Z',
    },
    {
        id: 'artifact-diff',
        team_id: 1,
        run_id: run.id,
        artifact_type: 'git_diff',
        size_bytes: 2048,
        content_hash: 'hash',
        additions: 12,
        removals: 3,
        created_at: '2026-09-23T10:02:00Z',
    },
]

const meta: Meta<typeof WizardInstallSyncView> = {
    title: 'Products/Wizard/Wizard install sync',
    component: WizardInstallSyncView,
    parameters: { layout: 'centered', testOptions: { waitForLoadersToDisappear: false } },
    decorators: [
        (Story) => (
            <div className="w-96">
                <Story />
            </div>
        ),
    ],
    argTypes: {
        run: { control: 'object' },
        tasks: { control: 'object' },
        artifacts: { control: 'object' },
        now: { control: 'number' },
        loading: { control: 'boolean' },
        error: { control: 'text' },
    },
    args: {
        run,
        now: NOW,
        tasks: [
            task('Install the PostHog SDK', 'completed'),
            task('Add your project token', 'running'),
            task('Verify events', 'created'),
        ],
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const RunningWithTasks: Story = {}

export const RunningWithoutTasks: Story = {
    args: { tasks: [] },
}

export const WithArtifacts: Story = {
    args: {
        run: {
            ...run,
            environment: 'cloud',
            workspace: { type: 'git_repository', repository: 'example/project' },
            status: 'completed',
            finished_at: '2026-09-23T10:03:00Z',
        },
        tasks: [],
        artifacts: [artifacts[1], artifacts[0]],
    },
}

export const CompletedLocally: Story = {
    args: { run: { ...run, status: 'completed', finished_at: '2026-09-23T10:03:00Z' }, tasks: [] },
}

export const Canceled: Story = {
    args: { run: { ...run, status: 'cancelled', finished_at: '2026-09-23T10:03:00Z' }, tasks: [] },
}

export const LoadingArtifacts: Story = {
    args: { ...WithArtifacts.args, artifacts: [], loading: true },
}

export const ArtifactLoadFailed: Story = {
    args: { ...WithArtifacts.args, artifacts: [], error: "Couldn't load tasks and artifacts. Try again." },
}

export const ManyTasks: Story = {
    args: {
        tasks: [
            task('Detect your framework', 'completed'),
            task('Install the PostHog SDK', 'completed'),
            task('Add your project token', 'running'),
            task('Verify events', 'created'),
            task('Open a pull request', 'created'),
        ],
    },
}

export const Starting: Story = {
    args: {
        run: { ...run, status: 'created', stage: 'dispatching' },
        tasks: [],
    },
}

export const Failed: Story = {
    args: {
        run: {
            ...run,
            status: 'failed',
            stage: 'executing_wizard',
            error_code: 'execution_failed',
            error_message: 'Could not install posthog-js: the package manager exited with code 1.',
            finished_at: '2026-09-23T10:03:00Z',
        },
        tasks: [task('Install the PostHog SDK', 'completed'), task('Add your project token', 'failed')],
    },
}
