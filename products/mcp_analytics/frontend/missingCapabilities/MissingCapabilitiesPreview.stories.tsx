import { Meta, StoryObj } from '@storybook/react'

import { MissingCapabilitiesPreview } from './MissingCapabilitiesPreview'

const meta: Meta = {
    title: 'Scenes-App/MCP Analytics/Missing Capabilities Preview',
    parameters: { layout: 'padded' },
}
export default meta

type Story = StoryObj

// Snapshotted at the width the empty state's preview column gives it, so the asks wrap the way
// they do in the tab. The stagger animation is disabled under storybook, so this is stable.
export const ExampleReports: Story = {
    render: () => (
        <div className="w-[420px]">
            <MissingCapabilitiesPreview />
        </div>
    ),
}
