import type { Meta, StoryObj } from '@storybook/react'

import { TaskActionsMenu } from './TaskActionsMenu'

const meta: Meta<typeof TaskActionsMenu> = {
    title: 'Products/PostHog AI/TaskActionsMenu',
    component: TaskActionsMenu,
    args: {
        title: 'Fix the flaky replay export test',
        onRename: () => {},
    },
    decorators: [
        (Story) => (
            <div className="flex justify-end w-64 p-3">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}
