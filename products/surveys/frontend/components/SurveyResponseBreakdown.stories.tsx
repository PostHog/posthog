import type { Meta, StoryObj } from '@storybook/react'

import { getSurveyResponseOutcomeBreakdown } from 'scenes/surveys/utils'

import { SurveyResponseBreakdown } from './SurveyResponseBreakdown'

const meta: Meta<typeof SurveyResponseBreakdown> = {
    title: 'Surveys/SurveyResponseBreakdown',
    component: SurveyResponseBreakdown,
    decorators: [
        (Story, { parameters }) => (
            <div style={{ width: parameters.width ?? 960 }}>
                <Story />
            </div>
        ),
    ],
    args: { outcomes: getSurveyResponseOutcomeBreakdown([2, 1, 2]) },
}
export default meta

type Story = StoryObj<typeof meta>

export const Mixed: Story = {}
export const Empty: Story = { args: { outcomes: getSurveyResponseOutcomeBreakdown([0, 0, 0]) } }
export const DismissalOnly: Story = { args: { outcomes: getSurveyResponseOutcomeBreakdown([0, 3, 0]) } }
export const AbandonmentOnly: Story = { args: { outcomes: getSurveyResponseOutcomeBreakdown([0, 0, 3]) } }
export const Narrow: Story = { parameters: { width: 512 } }
