import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ContentAutopilotPromptsMemoryVsSearch } from './ContentAutopilotPromptsMemoryVsSearch'

const meta: Meta<typeof ContentAutopilotPromptsMemoryVsSearch> = {
    title: 'Products/Web Analytics/Content autopilot/Memory vs search',
    component: ContentAutopilotPromptsMemoryVsSearch,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
        testOptions: { snapshotBrowsers: [] },
    },
}

export default meta

export const NoChecksWithoutSearchYet: StoryFn<typeof ContentAutopilotPromptsMemoryVsSearch> = () => (
    <div className="p-6 max-w-3xl">
        <ContentAutopilotPromptsMemoryVsSearch rows={[]} />
    </div>
)
