import type { Meta, StoryObj } from '@storybook/react'

import { WatchFeedBlockedBanner } from './WatchFeedBlockedBanner'

const meta: Meta<typeof WatchFeedBlockedBanner> = {
    title: 'Scenes-App/Replay Vision/WatchFeedBlockedBanner',
    component: WatchFeedBlockedBanner,
    decorators: [
        // LemonBanner is a CSS container, so the width has to come from the parent. This is the feed's width.
        (Story) => (
            <div className="w-200">
                <Story />
            </div>
        ),
    ],
}
export default meta

export const QuotaExhausted: StoryObj<typeof WatchFeedBlockedBanner> = { args: { reason: 'quota-exhausted' } }
