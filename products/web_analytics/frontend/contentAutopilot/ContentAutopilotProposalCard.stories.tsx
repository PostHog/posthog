import type { Meta, StoryFn } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

import { ContentAutopilotProposalCard } from './ContentAutopilotProposalCard'
import { EXAMPLE_PROPOSAL_LIST } from './contentAutopilotStoryFixtures'

const meta: Meta<typeof ContentAutopilotProposalCard> = {
    title: 'Products/Web Analytics/Content autopilot/Proposal card',
    component: ContentAutopilotProposalCard,
    parameters: {
        layout: 'centered',
        featureFlags: [FEATURE_FLAGS.WEB_ANALYTICS_PAGE_PERFORMANCE, FEATURE_FLAGS.WEB_ANALYTICS_CONTENT_AUTOPILOT],
    },
}

export default meta

export const ReadyForReview: StoryFn<typeof ContentAutopilotProposalCard> = () => (
    <div className="w-[640px]">
        <ContentAutopilotProposalCard proposal={EXAMPLE_PROPOSAL_LIST} onReview={() => undefined} />
    </div>
)

export const BlockingValidation: StoryFn<typeof ContentAutopilotProposalCard> = () => (
    <div className="w-[640px]">
        <ContentAutopilotProposalCard
            proposal={{
                ...EXAMPLE_PROPOSAL_LIST,
                lifecycle_status: 'failed',
                validation_report: {
                    passed: false,
                    checks: [
                        {
                            check_key: 'factual_sources',
                            label: 'Factual sourcing',
                            passed: false,
                            message: 'One factual claim has no public source.',
                            blocking: true,
                        },
                    ],
                },
            }}
            onReview={() => undefined}
        />
    </div>
)
