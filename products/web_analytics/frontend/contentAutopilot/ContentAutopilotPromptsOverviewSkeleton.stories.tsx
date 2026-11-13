import type { Meta, StoryFn } from '@storybook/react'

import { ContentAutopilotPromptsOverviewSkeleton } from './ContentAutopilotPromptsOverviewSkeleton'

const meta: Meta<typeof ContentAutopilotPromptsOverviewSkeleton> = {
    title: 'Products/Web Analytics/Content autopilot/Prompts overview skeleton',
    component: ContentAutopilotPromptsOverviewSkeleton,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

export const Loading: StoryFn<typeof ContentAutopilotPromptsOverviewSkeleton> = () => (
    <div className="p-6">
        <ContentAutopilotPromptsOverviewSkeleton />
    </div>
)
