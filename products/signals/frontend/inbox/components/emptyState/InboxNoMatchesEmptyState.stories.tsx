import type { Meta, StoryObj } from '@storybook/react'

import { InboxNoMatchesEmptyState } from './InboxNoMatchesEmptyState'

const meta: Meta<typeof InboxNoMatchesEmptyState> = {
    title: 'Scenes-App/Inbox/NoMatchesEmptyState',
    component: InboxNoMatchesEmptyState,
    args: {
        onClearFilters: () => {},
        onShowEntireProject: () => {},
    },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export default meta

type Story = StoryObj<typeof InboxNoMatchesEmptyState>

export const NarrowedByFilters: Story = { args: { narrowedBy: 'filters' } }

export const NarrowedToForYou: Story = { args: { narrowedBy: 'for-you' } }

export const NarrowedToATeammate: Story = { args: { narrowedBy: 'teammate' } }
