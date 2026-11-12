import type { Meta, StoryFn } from '@storybook/react'

import { ContentAutopilotKeywordsSkeleton } from './ContentAutopilotKeywordsSkeleton'

const meta: Meta<typeof ContentAutopilotKeywordsSkeleton> = {
    title: 'Products/Web Analytics/Content autopilot/Keywords skeleton',
    component: ContentAutopilotKeywordsSkeleton,
    parameters: {
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

export const Loading: StoryFn<typeof ContentAutopilotKeywordsSkeleton> = () => (
    <div className="p-6">
        <ContentAutopilotKeywordsSkeleton />
    </div>
)
