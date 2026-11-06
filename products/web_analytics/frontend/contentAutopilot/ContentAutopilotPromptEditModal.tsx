import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    aeoPromptsPartialUpdateBodyPromptMax,
    aeoPromptsPartialUpdateBodyTopicMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

export const ContentAutopilotPromptEditModal = (): JSX.Element | null => {
    const { prompt, promptEditing, promptSaving } = useValues(contentAutopilotPromptDetailLogic)
    const { savePromptEdit, setPromptEditing } = useActions(contentAutopilotPromptDetailLogic)
    const [text, setText] = useState('')
    const [topic, setTopic] = useState('')

    useEffect(() => {
        if (promptEditing && prompt) {
            setText(prompt.prompt)
            setTopic(prompt.topic)
        }
    }, [promptEditing, prompt])

    if (!prompt) {
        return null
    }

    const close = (): void => setPromptEditing(false)

    return (
        <LemonModal
            isOpen={promptEditing}
            onClose={promptSaving ? undefined : close}
            title="Edit prompt"
            description="A text change adds a new version. Past checks keep the version they ran with."
            width={640}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={close}
                        disabledReason={promptSaving ? 'Wait for the prompt to save' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={() => savePromptEdit(text, topic)}
                        loading={promptSaving}
                        disabledReason={!text.trim() ? 'Enter the prompt text' : undefined}
                        data-attr="content-autopilot-prompt-edit-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-4">
                <LemonField.Pure label="Prompt">
                    <LemonTextArea
                        value={text}
                        onChange={setText}
                        minRows={3}
                        maxLength={aeoPromptsPartialUpdateBodyPromptMax}
                        autoFocus
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Topic" help="Leave empty to remove the topic.">
                    <LemonInput value={topic} onChange={setTopic} maxLength={aeoPromptsPartialUpdateBodyTopicMax} />
                </LemonField.Pure>
            </div>
        </LemonModal>
    )
}
