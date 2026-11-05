import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import type { WizardRunApi, WizardRunArtifactApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { WizardSpendAuditModalView, type WizardSpendAuditModalViewProps } from './WizardSpendAuditModalView'

const NOW = new Date('2026-09-23T10:03:00Z').getTime()

const run: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000002',
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/web-app' },
    program: {
        id: 'spend-audit',
        name: 'Spend audit',
        description: 'Find ways to lower your PostHog bill',
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

const task = (name: string, status: WizardRunTaskApi['status']): WizardRunTaskApi => ({
    name,
    status,
    created_at: '2026-09-23T10:00:00Z',
    started_at: status === 'created' ? null : '2026-09-23T10:01:00Z',
    completed_at: status === 'completed' ? '2026-09-23T10:02:00Z' : null,
    failed_at: status === 'failed' ? '2026-09-23T10:02:00Z' : null,
    error_message: null,
})

const pullRequest: WizardRunArtifactApi = {
    id: 'artifact-pr',
    team_id: 1,
    run_id: run.id,
    artifact_type: 'pull_request',
    url: 'https://github.com/example/web-app/pull/42',
    number: 42,
    repository: 'example/web-app',
    head_branch: 'posthog/spend-audit',
    base_branch: 'main',
    created_at: '2026-09-23T10:02:00Z',
}

const baseProps: WizardSpendAuditModalViewProps = {
    isOpen: true,
    view: 'pick_repository',
    repository: '',
    githubIntegrationId: 1,
    connectGitHubUrl: '/api/environments/1/integrations/authorize?kind=github',
    setupError: null,
    creating: false,
    createError: null,
    run: null,
    tasks: [],
    artifacts: [],
    runDataLoading: false,
    runDataError: null,
    now: NOW,
    onClose: () => {},
    onRepositoryChange: () => {},
    onStart: () => {},
    onRetrySetup: () => {},
    onRunAgain: () => {},
    onRetryRunData: () => {},
}

const meta: Meta<typeof WizardSpendAuditModalView> = {
    title: 'Products/Wizard/Spend audit modal',
    component: WizardSpendAuditModalView,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-09-23T10:03:00Z',
        testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/integrations/:id/github_repos/': {
                    repositories: [
                        { id: 1, name: 'web-app', full_name: 'example/web-app', default_branch: 'main' },
                        { id: 2, name: 'api', full_name: 'example/api', default_branch: 'main' },
                    ],
                    has_more: false,
                    next: null,
                    previous: null,
                    next_offset: null,
                    total: 2,
                },
            },
        }),
    ],
    args: baseProps,
}
export default meta

type Story = StoryObj<typeof WizardSpendAuditModalView>

export const ConnectGitHub: Story = {
    args: { view: 'connect_github', githubIntegrationId: null },
}

export const PickRepository: Story = {
    args: { view: 'pick_repository', repository: 'example/web-app' },
}

export const Running: Story = {
    args: {
        view: 'run',
        run,
        tasks: [
            task('Audit the PostHog setup', 'completed'),
            task('Build the audit dashboard', 'running'),
            task('Open pull request: trim autocapture', 'created'),
        ],
    },
}

export const Completed: Story = {
    args: {
        view: 'run',
        run: { ...run, status: 'completed', stage: 'creating_artifacts', finished_at: '2026-09-23T10:02:30Z' },
        tasks: [],
        artifacts: [pullRequest],
    },
}

export const Failed: Story = {
    args: {
        view: 'run',
        run: {
            ...run,
            status: 'failed',
            stage: 'executing_wizard',
            finished_at: '2026-09-23T10:02:30Z',
            error_message: 'The audit could not read the repository: the default branch has no package manifest.',
        },
        tasks: [task('Audit the PostHog setup', 'failed')],
    },
}

export const Unavailable: Story = {
    args: { view: 'unavailable' },
}
