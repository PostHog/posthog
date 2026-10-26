import type { Meta, StoryObj } from '@storybook/react'

import { WatchFeedBlockedBanner } from './WatchFeedBlockedBanner'

const meta: Meta<typeof WatchFeedBlockedBanner> = {
    title: 'Scenes-App/Replay Vision/WatchFeedBlockedBanner',
    component: WatchFeedBlockedBanner,
    decorators: [
        // LemonBanner is a CSS container, so the parent sets its width.
        (Story) => (
            <div className="w-200">
                <Story />
            </div>
        ),
    ],
}
export default meta

export const QuotaExhausted: StoryObj<typeof WatchFeedBlockedBanner> = { args: { reason: 'quota-exhausted' } }
