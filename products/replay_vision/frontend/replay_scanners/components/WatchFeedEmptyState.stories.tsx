import type { Meta, StoryObj } from '@storybook/react'

import { WatchFeedEmptyState } from './WatchFeedEmptyState'

// One story per reason: the copy is the feature here, so a screenshot is the only way to check that
// each one reads as a different answer with a different next step.
const meta: Meta<typeof WatchFeedEmptyState> = {
    title: 'Scenes-App/Replay Vision/WatchFeedEmptyState',
    component: WatchFeedEmptyState,
    decorators: [
        // The width has to come from the parent. LemonBanner is a CSS container, so its contents do
        // not set its width, and the snapshot runner sizes the story root to hug its child — which
        // collapses a bannered story to a strip. This is also the width the feed renders at.
        (Story) => (
            <div className="w-200">
                <Story />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof WatchFeedEmptyState>

export const NoScanners: Story = { args: { reason: 'no-scanners' } }
export const AllDisabled: Story = { args: { reason: 'all-disabled' } }
export const QuotaExhausted: Story = { args: { reason: 'quota-exhausted' } }
export const AllCapped: Story = { args: { reason: 'all-capped' } }
export const Filtered: Story = { args: { reason: 'filtered' } }
export const QuietWindow: Story = { args: { reason: 'quiet-window' } }
