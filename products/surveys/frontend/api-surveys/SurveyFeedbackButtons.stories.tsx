import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { SurveyFeedbackButtons } from './SurveyFeedbackButtons'

const meta: Meta<typeof SurveyFeedbackButtons> = {
    title: 'Surveys/Feedback buttons',
    component: SurveyFeedbackButtons,
    args: { onMoreFeedback: () => {} },
    render: function Render(args) {
        const [value, setValue] = useState(args.value)
        return (
            <div className="w-96 max-w-full">
                <SurveyFeedbackButtons {...args} value={value} onChange={setValue} />
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
