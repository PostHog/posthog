import type { Meta, StoryFn } from '@storybook/react'

import { ContentAutopilotPromptDetailSkeleton } from './ContentAutopilotPromptDetailSkeleton'

const meta: Meta<typeof ContentAutopilotPromptDetailSkeleton> = {
    title: 'Products/Web Analytics/Content autopilot/Prompt page skeleton',
    component: ContentAutopilotPromptDetailSkeleton,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

export const Loading: StoryFn<typeof ContentAutopilotPromptDetailSkeleton> = () => (
    <div className="p-6">
        <ContentAutopilotPromptDetailSkeleton />
    </div>
)
