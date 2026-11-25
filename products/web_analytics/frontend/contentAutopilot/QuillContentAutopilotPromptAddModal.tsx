import { useId } from 'react'

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

export const QuillContentAutopilotPromptAddModal = ({
    open,
    submitting,
    text,
    topic,
    topicMaxLength,
    submitLabel,
    disabledReason,
    onTextChange,
    onTopicChange,
    onSubmit,
    onClose,
}: {
    open: boolean
    submitting: boolean
    text: string
    topic: string
    topicMaxLength: number
    submitLabel: string
    disabledReason: string | undefined
    onTextChange: (text: string) => void
    onTopicChange: (topic: string) => void
    onSubmit: () => void
    onClose: () => void
}): JSX.Element => {
    const id = useId()

    return (
        // While the prompts save, the dialog stays open, as the Lemon modal does.
        <Credenza open={open} onOpenChange={(next) => !next && !submitting && onClose()}>
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
                            onChange={(event) => onTextChange(event.target.value)}
                            rows={6}
                            placeholder="What's the best open source session replay tool?"
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
                            onChange={(event) => onTopicChange(event.target.value)}
                            maxLength={topicMaxLength}
                            placeholder="Session replay"
                        />
                        <FieldDescription>Optional. Groups the prompts in the overview and the list.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={onClose}
                        disabledReason={submitting ? 'Wait for the prompts to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSubmit}
                        loading={submitting}
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
