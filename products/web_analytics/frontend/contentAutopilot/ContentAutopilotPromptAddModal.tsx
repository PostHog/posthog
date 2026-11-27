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
    Input,
    Textarea,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import {
    aeoPromptsBulkImportBodyPromptsItemTopicMax,
    aeoPromptsBulkImportBodyPromptsMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { promptLines } from './utils'

export const ContentAutopilotPromptAddModal = (): JSX.Element => {
    const { addPromptsOpen, addPromptsSubmitting } = useValues(contentAutopilotPromptsLogic)
    const { addPrompts, closeAddPrompts } = useActions(contentAutopilotPromptsLogic)
    const [text, setText] = useState('')
    const [topic, setTopic] = useState('')
    const id = useId()

    useEffect(() => {
        if (!addPromptsOpen) {
            setText('')
            setTopic('')
        }
    }, [addPromptsOpen])

    const count = promptLines(text).length
    const disabledReason =
        count === 0
            ? 'Enter at least one prompt'
            : count > aeoPromptsBulkImportBodyPromptsMax
              ? `Add up to ${aeoPromptsBulkImportBodyPromptsMax} prompts at a time`
              : undefined
    const submitLabel = count > 0 ? `Add ${pluralize(count, 'prompt')}` : 'Add prompts'

    return (
        // While the prompts save, the dialog stays open.
        <Credenza open={addPromptsOpen} onOpenChange={(next) => !next && !addPromptsSubmitting && closeAddPrompts()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Add prompts</CredenzaTitle>
                    <CredenzaDescription>
                        Write each prompt the way a person would ask an AI assistant.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody className="flex flex-col gap-4">
                    <Field>
                        <FieldLabel htmlFor={`${id}-prompts`}>Prompts</FieldLabel>
                        <Textarea
                            id={`${id}-prompts`}
                            value={text}
                            onChange={(event) => setText(event.target.value)}
                            rows={6}
                            placeholder="What's the best scheduling software for a dental clinic?"
                            autoFocus
                            data-attr="content-autopilot-prompts-add-text"
                        />
                        <FieldDescription>
                            One prompt per line. A prompt that is already tracked gets the topic below.
                        </FieldDescription>
                    </Field>
                    <Field>
                        <FieldLabel htmlFor={`${id}-topic`}>Topic</FieldLabel>
                        <Input
                            id={`${id}-topic`}
                            value={topic}
                            onChange={(event) => setTopic(event.target.value)}
                            maxLength={aeoPromptsBulkImportBodyPromptsItemTopicMax}
                            placeholder="Scheduling software"
                        />
                        <FieldDescription>Optional. Groups the prompts in the overview and the list.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={closeAddPrompts}
                        disabledReason={addPromptsSubmitting ? 'Wait for the prompts to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => addPrompts(text, topic)}
                        loading={addPromptsSubmitting}
                        disabledReason={disabledReason}
                        data-attr="content-autopilot-prompts-add-submit"
                    >
                        {submitLabel}
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
