import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ContentAutopilotBriefPanel } from './ContentAutopilotBriefPanel'
import { EXAMPLE_PROPOSAL } from './contentAutopilotStoryFixtures'

const meta: Meta<typeof ContentAutopilotBriefPanel> = {
    title: 'Products/Web Analytics/Content autopilot/Brief',
    component: ContentAutopilotBriefPanel,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE, FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
}

export default meta

export const Brief: StoryFn<typeof ContentAutopilotBriefPanel> = () => (
    <div className="max-w-3xl p-4">
        <ContentAutopilotBriefPanel brief={EXAMPLE_PROPOSAL.brief} evidence={EXAMPLE_PROPOSAL.evidence} />
    </div>
)

export const MissingBrief: StoryFn<typeof ContentAutopilotBriefPanel> = () => (
    <div className="max-w-3xl p-4">
        <ContentAutopilotBriefPanel brief={{}} evidence={[]} />
    </div>
)
