import { Meta, StoryObj } from '@storybook/react'

import { ShipIt } from './ShipIt'

const meta: Meta<typeof ShipIt> = {
    title: 'Games/Ship It',
    component: ShipIt,
    parameters: {
        docs: {
            description: {
                component:
                    'Steer a pull request between three lanes to collect approvals and green CI, and to dodge conflicts, flaky tests and the stale bot. Progress toward the merge queue only accrues while CI is green and both approvals hold. Nothing moves until the player starts, so this renders the same every time.',
            },
        },
    },
    tags: ['autodocs'],
}
export default meta

type Story = StoryObj<typeof ShipIt>

export const Default: Story = {}

export const NarrowScene: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px]">
                <Story />
            </div>
        ),
    ],
}
