import type { Meta, StoryObj } from '@storybook/react'

import { ScoutCreateModalSkeleton } from './ScoutCreateModalSkeleton'

const meta: Meta = {
    title: 'Scenes-Inbox/Scout loading states',
    parameters: {
        layout: 'fullscreen',
        testOptions: { waitForSelector: '[aria-label="Loading scout form"]', viewport: { width: 1200, height: 900 } },
    },
}

export default meta

type Story = StoryObj

export const CreateScoutModal: Story = {
    render: () => <ScoutCreateModalSkeleton />,
}
