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

export const QuillContentAutopilotPromptEditModal = ({
    open,
    saving,
    text,
    topic,
    promptMaxLength,
    topicMaxLength,
    onTextChange,
    onTopicChange,
    onSave,
    onClose,
}: {
    open: boolean
    saving: boolean
    text: string
    topic: string
    promptMaxLength: number
    topicMaxLength: number
    onTextChange: (text: string) => void
    onTopicChange: (topic: string) => void
    onSave: () => void
    onClose: () => void
}): JSX.Element => {
    const id = useId()

    return (
        // While the prompt saves, the dialog stays open, as the Lemon modal does.
        <Credenza open={open} onOpenChange={(next) => !next && !saving && onClose()}>
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
                            onChange={(event) => onTextChange(event.target.value)}
                            rows={3}
                            maxLength={promptMaxLength}
                            autoFocus
                        />
                    </Field>
                    <Field>
                        <FieldLabel htmlFor={`${id}-topic`}>Topic</FieldLabel>
                        <Input
                            id={`${id}-topic`}
                            value={topic}
                            onChange={(event) => onTopicChange(event.target.value)}
                            maxLength={topicMaxLength}
                        />
                        <FieldDescription>Leave empty to remove the topic.</FieldDescription>
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={onClose}
                        disabledReason={saving ? 'Wait for the prompt to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={onSave}
                        loading={saving}
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
