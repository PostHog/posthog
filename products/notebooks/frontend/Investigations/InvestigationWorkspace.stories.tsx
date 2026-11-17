import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { newInvestigation } from './investigationDocument'
import { investigationExample } from './investigationExample'
import { InvestigationWorkspace } from './InvestigationWorkspace'

const meta: Meta<typeof InvestigationWorkspace> = {
    title: 'Scenes-App/Notebooks/Investigations/Workspace',
    component: InvestigationWorkspace,
    parameters: { mockDate: '2026-11-10T12:00:00Z', testOptions: { snapshotBrowsers: [] } },
    decorators: [
        (Story) => (
            <div className="p-6 max-w-6xl">
                <Story />
            </div>
        ),
        mswDecorator({
            post: {
                '/api/environments/:team_id/query/:kind': {
                    columns: ['conversion_rate'],
                    results: [[18.4]],
                    hasMore: false,
                },
            },
        }),
    ],
    args: { scope: 'investigation-story', editable: true, onChange: () => {} },
}
export default meta
type Story = StoryObj<typeof meta>

export const Empty: Story = { args: { document: newInvestigation() } }
export const WorkedExample: Story = { args: { document: investigationExample() } }
export const ReadOnly: Story = { args: { document: investigationExample(), editable: false } }
