import { Meta, StoryObj } from '@storybook/react'

import { LemonButton } from '@posthog/lemon-ui'

import { exampleApiSurvey, exampleSurveyClient, exampleRatingSurvey, exampleFeedbackRating } from './apiSurvey.fixtures'
import { APISurveyFeedback } from './APISurveyFeedback'
import { APISurveyForm } from './APISurveyForm'

const meta: Meta<typeof APISurveyForm> = {
    title: 'Surveys/API survey form',
    component: APISurveyForm,
    args: {
        surveyId: exampleApiSurvey.id,
        instanceId: 'example-form',
        client: exampleSurveyClient(),
        context: { feedback_surface: 'storybook' },
    },
    decorators: [
        (Story, { parameters }) => (
            <div
                className={`${parameters.wide ? 'w-[800px]' : 'w-[520px]'} max-w-full rounded border border-primary bg-surface-primary p-4`}
            >
                <Story />
            </div>
        ),
    ],
}
export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Wide: Story = {
    parameters: { wide: true },
}
export const Unavailable: Story = { args: { client: exampleSurveyClient([]) } }
export const Loading: Story = {
    args: { client: { ...exampleSurveyClient(), getSurveys: () => {} } },
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
}
export const LoadError: Story = {
    args: {
        client: {
            ...exampleSurveyClient(),
            getSurveys: () => {
                throw new Error('Example failure')
            },
        },
    },
}
export const SubmissionError: Story = { args: { client: { ...exampleSurveyClient(), capture: () => undefined } } }

export const KeyboardNavigation: Story = {
    render: (args) => (
        <div className="space-y-4">
            <LemonButton>Before the survey</LemonButton>
            <APISurveyForm {...args} />
            <LemonButton>After the survey</LemonButton>
        </div>
    ),
}

export const Dialog: Story = {
    args: { client: exampleSurveyClient([exampleRatingSurvey]) },
    render: (args) => <APISurveyFeedback {...args} />,
}

export const NumericRating: Story = {
    ...Dialog,
    args: {
        client: exampleSurveyClient([
            {
                ...exampleRatingSurvey,
                questions: [
                    {
                        ...exampleFeedbackRating,
                        display: 'number',
                        scale: 10,
                        question: 'How likely are you to recommend this?',
                        lowerBoundLabel: 'Not likely',
                        upperBoundLabel: 'Very likely',
                    },
                    ...exampleRatingSurvey.questions.slice(1),
                ],
            },
        ]),
    },
}

export const FeedbackLoading: Story = { ...Dialog, args: Loading.args, parameters: Loading.parameters }
export const FeedbackUnavailable: Story = { ...Dialog, args: Unavailable.args }

export const RatingWithoutPartialResponses: Story = {
    ...Dialog,
    args: { client: exampleSurveyClient([{ ...exampleRatingSurvey, enable_partial_responses: false }]) },
}
