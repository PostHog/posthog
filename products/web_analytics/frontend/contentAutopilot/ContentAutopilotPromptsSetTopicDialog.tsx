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
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { aeoPromptsBulkSetTopicBodyTopicMax } from 'products/web_analytics/frontend/generated/api.zod'

import { AiVisibilityTopicInput } from './AiVisibilityTopicInput'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'

/** Sets one topic on the prompts picked in the list. */
export const ContentAutopilotPromptsSetTopicDialog = (): JSX.Element => {
    const { setTopicOpen, setTopicSaving, selectedPromptIds } = useValues(contentAutopilotPromptsLogic)
    const { closeSetTopic, setPromptsTopic } = useActions(contentAutopilotPromptsLogic)
    const [topic, setTopic] = useState('')
    const id = useId()

    useEffect(() => {
        if (!setTopicOpen) {
            setTopic('')
        }
    }, [setTopicOpen])

    const count = pluralize(selectedPromptIds.length, 'prompt')

    return (
        // While the topic saves, the dialog stays open.
        <Credenza open={setTopicOpen} onOpenChange={(next) => !next && !setTopicSaving && closeSetTopic()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Set topic</CredenzaTitle>
                    <CredenzaDescription>
                        Choose a topic for {count}. Their past answers keep the topic they had.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <Field>
                        <FieldLabel htmlFor={`${id}-topic`}>Topic</FieldLabel>
                        <AiVisibilityTopicInput
                            id={`${id}-topic`}
                            value={topic}
                            onChange={setTopic}
                            maxLength={aeoPromptsBulkSetTopicBodyTopicMax}
                            placeholder="Pick a topic or type a new one"
                            autoFocus
                            dataAttr="content-autopilot-prompts-set-topic-input"
                        />
                        <FieldDescription>Leave empty to remove the topic.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={closeSetTopic}
                        disabledReason={setTopicSaving ? 'Wait for the topic to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => setPromptsTopic(topic.trim())}
                        loading={setTopicSaving}
                        data-attr="content-autopilot-prompts-set-topic-submit"
                    >
                        {topic.trim() ? 'Set topic' : 'Remove topic'}
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
