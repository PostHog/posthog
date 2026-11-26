import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { NotebookAppSubmission } from './NotebookAppSubmission'

const meta: Meta<typeof NotebookAppSubmission> = {
    title: 'Scenes-App/Notebooks/Row actions',
    component: NotebookAppSubmission,
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/cohorts/from_selection': { cohort_id: 42 },
                '/api/projects/:team_id/hog_flows/:id/run': { status: 'queued', invocation_id: 'example-run' },
            },
        }),
    ],
    args: {
        project: '1',
        pendingInputs: false,
        columns: ['name', 'activation_step', 'person_id'],
        rows: [
            ['River', 'Invite a teammate', '00000000-0000-4000-8000-000000000001'],
            ['Sage', 'Create a dashboard', '00000000-0000-4000-8000-000000000002'],
            ['Linden', 'Capture a first event', '00000000-0000-4000-8000-000000000003'],
        ],
    },
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta

export const Cohort: StoryObj<typeof NotebookAppSubmission> = { args: { action: 'create_cohort' } }
export const Workflow: StoryObj<typeof NotebookAppSubmission> = {
    args: { action: 'run_workflow', workflowId: '00000000-0000-4000-8000-000000000042' },
}
