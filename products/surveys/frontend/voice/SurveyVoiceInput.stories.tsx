import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { LemonTextArea } from '@posthog/lemon-ui'

import { SurveyVoiceInput } from './SurveyVoiceInput'

const meta: Meta<typeof SurveyVoiceInput> = {
    title: 'Surveys/Voice input',
    component: SurveyVoiceInput,
    args: {
        id: 'example-voice-answer',
        transcribe: async () => 'I wanted to find the settings, but could not find the right page.',
    },
    render: function Render(args, { parameters }) {
        const [answer, setAnswer] = useState('')
        return (
            <div className={parameters.wide ? 'w-[800px] max-w-full space-y-4' : 'w-[520px] max-w-full space-y-4'}>
                <div className="text-xs text-secondary">
                    This story records locally and returns a sample transcript. It does not upload audio.
                </div>
                <SurveyVoiceInput {...args} onTranscript={setAnswer} />
                <LemonTextArea
                    aria-label="Your answer"
                    value={answer}
                    onChange={setAnswer}
                    placeholder="Type or record an answer"
                    minRows={3}
                />
            </div>
        )
    },
}
export default meta
type Story = StoryObj<typeof meta>

export const Default: Story = {}
export const Wide: Story = { parameters: { wide: true } }
export const Disabled: Story = { args: { disabled: true } }
export const TranscriptionError: Story = {
    args: {
        transcribe: async () => {
            throw new Error('Example transcription failure')
        },
    },
}
