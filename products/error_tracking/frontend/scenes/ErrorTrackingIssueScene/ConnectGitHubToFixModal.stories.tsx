import type { Meta, StoryObj } from '@storybook/react'

import { ConnectGitHubToFixModal } from './ConnectGitHubToFixModal'

const meta = {
    title: 'Error tracking/Connect GitHub to fix',
    component: ConnectGitHubToFixModal,
    args: {
        open: true,
        onOpenChange: () => undefined,
        onConnect: () => undefined,
        connectUrl: 'https://example.com/connect',
    },
    decorators: [
        (Story) => (
            <div className="min-h-screen w-full">
                <Story />
            </div>
        ),
    ],
} satisfies Meta<typeof ConnectGitHubToFixModal>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
