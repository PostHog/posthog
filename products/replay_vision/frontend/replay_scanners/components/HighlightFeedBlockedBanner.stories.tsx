import type { Meta, StoryObj } from '@storybook/react'

import { HighlightFeedBlockedBanner } from './HighlightFeedBlockedBanner'

const meta: Meta<typeof HighlightFeedBlockedBanner> = {
    title: 'Scenes-App/Replay Vision/HighlightFeedBlockedBanner',
    component: HighlightFeedBlockedBanner,
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

export const QuotaExhausted: StoryObj<typeof HighlightFeedBlockedBanner> = { args: { reason: 'quota-exhausted' } }
