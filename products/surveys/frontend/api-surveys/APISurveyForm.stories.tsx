import { Meta, StoryObj } from '@storybook/react'
import { useId, useState } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { exampleApiSurvey, exampleSurveyClient } from './apiSurvey.fixtures'
import { APISurveyForm } from './APISurveyForm'
import { SurveyFeedbackButtons, SurveyFeedbackRating } from './SurveyFeedbackButtons'

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
    render: (args, { parameters }) => {
        const [isOpen, setIsOpen] = useState(!!parameters.initiallyOpen)
        const titleId = useId()
        const [submissionId] = useState(() => crypto.randomUUID())
        const [rating, setRating] = useState<SurveyFeedbackRating | undefined>(
            parameters.initiallyOpen ? '1' : undefined
        )
        return (
            <>
                <SurveyFeedbackButtons
                    value={rating}
                    submissionId={submissionId}
                    onChange={setRating}
                    onMoreFeedback={() => setIsOpen(true)}
                    expanded={isOpen}
                />
                <LemonModal
                    isOpen={isOpen}
                    onClose={() => setIsOpen(false)}
                    title={<span id={titleId}>Share more feedback</span>}
                    contentRef={(element) => element?.setAttribute('aria-labelledby', titleId)}
                    width={520}
                    hasUnsavedInput
                >
                    {isOpen && (
                        <APISurveyForm
                            {...args}
                            submissionId={submissionId}
                            context={{ ...args.context, feedback_rating: rating }}
                        />
                    )}
                </LemonModal>
            </>
        )
    },
}

export const DialogOpen: Story = {
    ...Dialog,
    parameters: { initiallyOpen: true },
}
