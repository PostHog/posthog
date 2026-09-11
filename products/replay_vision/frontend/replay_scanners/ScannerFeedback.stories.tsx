import type { Meta, StoryObj } from '@storybook/react'
import { SurveyQuestionType, SurveyType } from 'posthog-js'
import { renderSurveysPreview } from 'posthog-js/dist/surveys-preview'
import { useEffect, useRef } from 'react'

const questions = {
    disabled: {
        question: 'Why did you disable this scanner?',
        description: 'Optional. Your scanner is already disabled.',
        choices: [
            'Too expensive',
            'Too many irrelevant findings',
            'Missed issues or inaccurate findings',
            'Not enough useful results',
            'Taking a break',
            'No longer needed',
            'Other',
        ],
    },
    deleted: {
        question: 'Why did you delete this scanner?',
        description: 'Optional. Your scanner is already deleted.',
        choices: [
            'Too expensive',
            'Too many irrelevant findings',
            'Missed issues or inaccurate findings',
            'Not enough useful results',
            'Replaced by another scanner',
            'Only testing',
            'No longer needed',
            'Other',
        ],
    },
    enabled: {
        question: 'What do you want this scanner to help you do?',
        choices: [
            'Find bugs',
            'Find where users get stuck',
            'Check a recent change',
            'Monitor a specific flow',
            'Understand how people use the product',
            'Other',
        ],
    },
}

function ScannerFeedbackPreview({ action }: { action: keyof typeof questions }): JSX.Element {
    const container = useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (!container.current) {
            return
        }
        const parentElement = container.current
        renderSurveysPreview({
            survey: {
                id: `scanner-feedback-preview-${action}`,
                name: 'Scanner feedback preview',
                type: SurveyType.API,
                questions: [{ type: SurveyQuestionType.SingleChoice, ...questions[action], buttonText: 'Next' }],
                appearance: { maxWidth: '340px' },
            },
            parentElement,
            previewPageIndex: 0,
            positionStyles: { position: 'fixed', right: '20px', bottom: '20px', left: 'auto', top: 'auto' },
        })
        return () => parentElement.replaceChildren()
    }, [action])
    return <div ref={container} />
}

const meta: Meta<typeof ScannerFeedbackPreview> = {
    title: 'Replay Vision/Scanner feedback',
    component: ScannerFeedbackPreview,
    parameters: { layout: 'fullscreen' },
    args: { action: 'disabled' },
}
export default meta

type Story = StoryObj<typeof meta>

export const Disabled: Story = {}
export const Deleted: Story = { args: { action: 'deleted' } }
export const Enabled: Story = { args: { action: 'enabled' } }
