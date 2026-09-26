import { Meta, StoryObj } from '@storybook/react'
import { SurveyQuestionType } from 'posthog-js'
import { useState } from 'react'

import { exampleApiSurvey } from './apiSurvey.fixtures'
import { APISurveyQuestion } from './APISurveyQuestion'

const meta: Meta<typeof APISurveyQuestion> = {
    title: 'Surveys/API survey question',
    component: APISurveyQuestion,
    args: { question: exampleApiSurvey.questions[0] },
    render: function Render(args) {
        const [value, setValue] = useState(args.value)
        return (
            <div className="w-[520px] max-w-full">
                <APISurveyQuestion
                    {...args}
                    value={value}
                    onChange={setValue}
                    onToggleChoice={(choice, checked) =>
                        setValue(
                            checked
                                ? [...(Array.isArray(value) ? value : []), choice]
                                : (Array.isArray(value) ? value : []).filter((value) => value !== choice)
                        )
                    }
                />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Text: Story = {}
export const SingleChoice: Story = { args: { question: exampleApiSurvey.questions[1] } }
export const Rating: Story = { args: { question: exampleApiSurvey.questions[2] } }
export const MultipleChoice: Story = { args: { question: exampleApiSurvey.questions[3] } }

export const EmojiRating: Story = {
    args: {
        question: {
            id: 'thumbs',
            type: SurveyQuestionType.Rating,
            question: 'Was this helpful?',
            display: 'emoji',
            scale: 2,
            lowerBoundLabel: 'Helpful',
            upperBoundLabel: 'Not helpful',
        },
    },
}
