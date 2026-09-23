import type { Meta, StoryObj } from '@storybook/react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { WizardRunSyncCard } from './WizardRunSyncCard'

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
    parameters: { layout: 'fullscreen' },
    args: {
        run,
        activeCount: 3,
        tasks: [
            task('Identify the existing analytics integration', 'completed'),
            task('Install the SDK and configure capture', 'running'),
            task('Verify events in PostHog', 'created'),
        ],
        onOpen: () => {},
    },
}

export default meta
type Story = StoryObj<typeof meta>

export const Running: Story = {}

export const LocalRunning: Story = {
    args: {
        run: {
            ...run,
            environment: 'local',
            workspace: { type: 'local_folder', project_name: 'example-project' },
            stage: null,
        },
        activeCount: 1,
    },
}
