import type { Meta, StoryObj } from '@storybook/react'

import { ScoutReportActionsTag } from './ScoutReportActionsTag'

const meta: Meta<typeof ScoutReportActionsTag> = {
    title: 'Scenes-App/Inbox/ScoutReportActionsTag',
    component: ScoutReportActionsTag,
    parameters: { testOptions: { snapshotBrowsers: [] } },
}
export default meta
type Story = StoryObj<typeof ScoutReportActionsTag>

export const Granted: Story = {
    render: () => (
        <div className="p-4">
            <ScoutReportActionsTag reportActions={['make_it_green', 'resolve_conflicts']} />
        </div>
    ),
}

export const DryRun: Story = {
    render: () => (
        <div className="p-4">
            <ScoutReportActionsTag reportActions={['make_it_green']} emit={false} />
        </div>
    ),
}
