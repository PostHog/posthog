import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { InboxPriorityFilter } from './InboxPriorityFilter'

const meta: Meta<typeof InboxPriorityFilter> = {
    title: 'Scenes-App/Inbox/PriorityFilter',
    component: InboxPriorityFilter,
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<typeof InboxPriorityFilter>

// Captures the open menu, so a change to the priority dot colors shows up next to the badges story.
export const Open: Story = {
    parameters: { testOptions: { snapshotTargetSelector: '.Popover' } },
    render: () => <InboxPriorityFilter />,
    play: async ({ canvasElement }) => {
        await userEvent.click(await within(canvasElement).findByText('All priorities'))
        await waitFor(() => {
            if (!document.querySelector('.Popover')) {
                throw new Error('priority menu not open yet')
            }
        })
    },
}
