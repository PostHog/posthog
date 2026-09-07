import type { Meta, StoryObj } from '@storybook/react'

import { ScoutWriteAccessTag } from './ScoutWriteAccessTag'

const meta: Meta<typeof ScoutWriteAccessTag> = {
    title: 'Scenes-App/Inbox/ScoutWriteAccessTag',
    component: ScoutWriteAccessTag,
}
export default meta
type Story = StoryObj<typeof ScoutWriteAccessTag>

export const Granted: Story = {
    render: () => (
        <div className="p-4">
            <ScoutWriteAccessTag writeScopes={['dashboard:write', 'insight:write']} />
        </div>
    ),
}

export const DryRun: Story = {
    render: () => (
        <div className="p-4">
            <ScoutWriteAccessTag writeScopes={['dashboard:write', 'insight:write']} emit={false} />
        </div>
    ),
}

export const Compact: Story = {
    render: () => (
        <div className="p-4">
            <ScoutWriteAccessTag
                writeScopes={['dashboard:write', 'insight:write', 'annotation:write', 'alert:write']}
                compact
            />
        </div>
    ),
}
