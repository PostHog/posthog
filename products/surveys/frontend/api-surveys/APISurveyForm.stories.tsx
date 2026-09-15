import { Meta, StoryObj } from '@storybook/react'

import { exampleApiSurvey, exampleSurveyClient } from './apiSurvey.fixtures'
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
