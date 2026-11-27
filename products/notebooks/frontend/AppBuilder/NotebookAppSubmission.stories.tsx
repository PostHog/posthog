import type { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'

import { mswDecorator } from '~/mocks/browser'

import { userEvent } from 'storybook/test'

import { NotebookAppSubmission } from './NotebookAppSubmission'

const meta: Meta<typeof NotebookAppSubmission> = {
    title: 'Scenes-App/Notebooks/Row actions',
    component: NotebookAppSubmission,
    decorators: [
        mswDecorator({
            get: { '/api/projects/:team_id/hog_flows/:id': { variables: [] } },
            post: {
                '/api/projects/:team_id/cohorts/from_selection': { cohort_id: 42 },
                '/api/projects/:team_id/hog_flows/:id/run': { status: 'queued', invocation_id: 'example-run' },
            },
        }),
    ],
    args: {
        sessionId: 'demo-app',
        draftKey: 'result-action',
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
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByLabelText('Select row 1'))
        await userEvent.click(canvas.getByRole('button', { name: 'Run workflow' }))
        await canvas.findByText('View workflow runs')
    },
}
