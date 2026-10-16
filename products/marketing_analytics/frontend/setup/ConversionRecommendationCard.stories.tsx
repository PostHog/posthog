import type { Meta, StoryObj } from '@storybook/react'

import { ConversionRecommendationCard } from './ConversionRecommendationCard'

const meta: Meta<typeof ConversionRecommendationCard> = {
    title: 'Scenes-App/Marketing Analytics/Conversion recommendation card',
    component: ConversionRecommendationCard,
    args: {
        recommendation: {
            source_ref: 'action:1',
            name: 'Qualified requests',
            reason: 'This action may represent qualified requests. Review its existing filters.',
            intent: 'conversion',
            state: 'needs_decision',
            questions: ['Does this action exclude test and duplicate requests?'],
            candidate: { source_ref: 'action:1', name: 'Qualified requests', kind: 'ActionsNode', action_id: 1 },
            draft: {
                goal: {
                    kind: 'ActionsNode',
                    id: 1,
                    conversion_goal_id: 'preview',
                    conversion_goal_name: 'Qualified requests',
                    schema_map: {},
                    math: 'total',
                },
                date_from: '2026-09-01T00:00:00Z',
                date_to: '2026-10-01T00:00:00Z',
            },
        },
        onReview: () => {},
    },
}
export default meta
type Story = StoryObj<typeof ConversionRecommendationCard>
export const Action: Story = {}
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-[520px] max-w-full">
                <Story />
            </div>
        ),
    ],
}
