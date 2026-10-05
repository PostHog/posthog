import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { exampleFeedbackRating } from './apiSurvey.fixtures'
import { SurveyFeedbackButtons } from './SurveyFeedbackButtons'

const meta: Meta<typeof SurveyFeedbackButtons> = {
    title: 'Surveys/Feedback buttons',
    component: SurveyFeedbackButtons,
    args: { question: exampleFeedbackRating, onMoreFeedback: () => {} },
    render: function Render(args) {
        const [value, setValue] = useState(args.value)
        const [submissionId] = useState(() => crypto.randomUUID())
        return (
            <div className="w-96 max-w-full">
                <SurveyFeedbackButtons {...args} value={value} submissionId={submissionId} onChange={setValue} />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Helpful: Story = { args: { value: '1' } }
export const NotHelpful: Story = { args: { value: '2' } }
export const Saving: Story = {
    args: { value: '1', loading: true },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const NumericRating: Story = {
    args: {
        question: {
            ...exampleFeedbackRating,
            display: 'number',
            scale: 5,
            question: 'How useful was this?',
            lowerBoundLabel: 'Not useful',
            upperBoundLabel: 'Very useful',
        },
    },
}
