import type { Meta, StoryFn } from '@storybook/react'

import { ContentAutopilotRankingsSkeleton } from './ContentAutopilotRankingsSkeleton'

const meta: Meta<typeof ContentAutopilotRankingsSkeleton> = {
    title: 'Products/Web Analytics/Content autopilot/Rankings skeleton',
    component: ContentAutopilotRankingsSkeleton,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

export const Loading: StoryFn<typeof ContentAutopilotRankingsSkeleton> = () => (
    <div className="p-6">
        <ContentAutopilotRankingsSkeleton />
    </div>
)
