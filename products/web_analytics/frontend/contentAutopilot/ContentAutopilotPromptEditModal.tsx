import { useActions, useValues } from 'kea'
import { useEffect, useId, useState } from 'react'

import {
    Button,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldDescription,
    FieldLabel,
    Textarea,
} from '@posthog/quill'

import {
    aeoPromptsPartialUpdateBodyPromptMax,
    aeoPromptsPartialUpdateBodyTopicMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { AiVisibilityTopicInput } from './AiVisibilityTopicInput'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

export const ContentAutopilotPromptEditModal = (): JSX.Element | null => {
    const { prompt, promptEditing, promptSaving } = useValues(contentAutopilotPromptDetailLogic)
    const { savePromptEdit, setPromptEditing } = useActions(contentAutopilotPromptDetailLogic)
    const [text, setText] = useState('')
    const [topic, setTopic] = useState('')
    const id = useId()

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
        // While the prompt saves, the dialog stays open.
        <Credenza open={promptEditing} onOpenChange={(next) => !next && !promptSaving && close()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Edit prompt</CredenzaTitle>
                    <CredenzaDescription>
                        A text change adds a new version. Past checks keep the version they ran with.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody className="flex flex-col gap-4">
                    <Field>
                        <FieldLabel htmlFor={`${id}-prompt`}>Prompt</FieldLabel>
                        <Textarea
                            id={`${id}-prompt`}
                            value={text}
                            onChange={(event) => setText(event.target.value)}
                            rows={3}
                            maxLength={aeoPromptsPartialUpdateBodyPromptMax}
                            autoFocus
                        />
                    </Field>
                    <Field>
                        <FieldLabel htmlFor={`${id}-topic`}>Topic</FieldLabel>
                        <AiVisibilityTopicInput
                            id={`${id}-topic`}
                            value={topic}
                            onChange={setTopic}
                            maxLength={aeoPromptsPartialUpdateBodyTopicMax}
                            dataAttr="content-autopilot-prompt-edit-topic"
                        />
                        <FieldDescription>Leave empty to remove the topic.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={close}
                        disabledReason={promptSaving ? 'Wait for the prompt to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => savePromptEdit(text, topic)}
                        loading={promptSaving}
                        disabledReason={!text.trim() ? 'Enter the prompt text' : undefined}
                        data-attr="content-autopilot-prompt-edit-save"
                    >
                        Save
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
