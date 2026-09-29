import type { Meta, StoryObj } from '@storybook/react'

import { WatchFeedEmptyState } from './WatchFeedEmptyState'

// One story per reason: the copy is the feature here, so a screenshot is the only way to check that
// each one reads as a different answer with a different next step.
const meta: Meta<typeof WatchFeedEmptyState> = {
    title: 'Scenes-App/Replay Vision/WatchFeedEmptyState',
    component: WatchFeedEmptyState,
}
export default meta

type Story = StoryObj<typeof WatchFeedEmptyState>

export const NoScanners: Story = { args: { reason: 'no-scanners' } }
export const AllDisabled: Story = { args: { reason: 'all-disabled' } }
export const QuotaExhausted: Story = { args: { reason: 'quota-exhausted' } }
export const AllCapped: Story = { args: { reason: 'all-capped' } }
export const Filtered: Story = { args: { reason: 'filtered' } }
export const QuietWindow: Story = { args: { reason: 'quiet-window' } }
