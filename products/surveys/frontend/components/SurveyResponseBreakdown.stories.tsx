import type { Meta, StoryObj } from '@storybook/react'

import { getSurveyResponseOutcomeBreakdown } from 'scenes/surveys/utils'

import { SurveyResponseBreakdown } from './SurveyResponseBreakdown'

const meta: Meta<typeof SurveyResponseBreakdown> = {
    title: 'Surveys/SurveyResponseBreakdown',
    component: SurveyResponseBreakdown,
    args: { outcomes: getSurveyResponseOutcomeBreakdown([2, 1, 2]) },
}
export default meta

type Story = StoryObj<typeof meta>

export const Mixed: Story = {}
export const Empty: Story = { args: { outcomes: getSurveyResponseOutcomeBreakdown([0, 0, 0]) } }
export const DismissalOnly: Story = { args: { outcomes: getSurveyResponseOutcomeBreakdown([0, 3, 0]) } }
export const Narrow: Story = {
    decorators: [
        (Story) => (
            <div className="w-96">
                <Story />
            </div>
        ),
    ],
}
