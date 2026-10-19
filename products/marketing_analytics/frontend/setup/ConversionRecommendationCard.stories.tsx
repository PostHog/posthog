import type { Meta, StoryObj } from '@storybook/react'

import { ConversionRecommendationCard } from './ConversionRecommendationCard'

const meta: Meta<typeof ConversionRecommendationCard> = {
    title: 'Scenes-App/Marketing Analytics/Conversion recommendation card',
    component: ConversionRecommendationCard,
    decorators: [
        (Story, { parameters }) => (
            <div className={parameters.narrow ? 'w-[520px] max-w-full' : 'w-240 max-w-full'}>
                <Story />
            </div>
        ),
    ],
    args: {
        onUseSuggestion: () => {},
        recommendation: {
            source_ref: 'action:1',
            name: 'Qualified requests',
            reason: 'This action may represent qualified requests. Review its existing filters.',
            intent: 'conversion',
            amount_property: null,
            questions: ['Does this action exclude test and duplicate requests?'],
            candidate: { source_ref: 'action:1', name: 'Qualified requests', kind: 'ActionsNode', action_id: 1 },
        },
    },
}
export default meta
type Story = StoryObj<typeof ConversionRecommendationCard>
export const Action: Story = {}
export const AlreadyConfigured: Story = {
    args: { alreadyConfigured: true },
    parameters: { narrow: true },
}
export const Narrow: Story = {
    parameters: { narrow: true },
    decorators: [],
}
