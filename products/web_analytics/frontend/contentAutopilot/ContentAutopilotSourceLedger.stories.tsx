import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ContentAutopilotSourceLedger } from './ContentAutopilotSourceLedger'
import { EXAMPLE_PROPOSAL } from './contentAutopilotStoryFixtures'

const meta: Meta<typeof ContentAutopilotSourceLedger> = {
    title: 'Products/Web Analytics/Content autopilot/Sources',
    component: ContentAutopilotSourceLedger,
    parameters: {
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE, FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
}

export default meta

export const WithResearchNotes: StoryFn<typeof ContentAutopilotSourceLedger> = () => (
    <div className="w-[720px] p-4">
        <ContentAutopilotSourceLedger
            entries={EXAMPLE_PROPOSAL.source_ledger}
            notes={["Couldn't read the cited page https://rival.example.com/replay."]}
        />
    </div>
)
