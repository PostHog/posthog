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
    FieldError,
    FieldLabel,
    Input,
} from '@posthog/quill'

import { aeoPromptsTopicsRenameBodyNewTopicMax } from 'products/web_analytics/frontend/generated/api.zod'

import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'

export const AiVisibilityTopicRenameDialog = (): JSX.Element => {
    const { topicDialog, topicChangeSaving, topicChangeError } = useValues(aiVisibilityTopicsLogic)
    const { closeTopicDialog, renameTopic } = useActions(aiVisibilityTopicsLogic)
    const open = topicDialog?.kind === 'rename'
    const topic = open ? topicDialog.topic : ''
    const [name, setName] = useState(topic)
    const id = useId()

    useEffect(() => {
        if (open) {
            setName(topic)
        }
    }, [open, topic])

    const trimmed = name.trim()
    const disabledReason = !trimmed ? 'Enter a name' : trimmed === topic ? 'Enter a different name' : undefined

    return (
        // While the topic saves, the dialog stays open.
        <Credenza open={open} onOpenChange={(next) => !next && !topicChangeSaving && closeTopicDialog()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Rename topic</CredenzaTitle>
                    <CredenzaDescription>
                        Every prompt in {topic} moves to the new name, archived ones included. Past answers show under
                        the new name too.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <Field data-invalid={topicChangeError ? true : undefined}>
                        <FieldLabel htmlFor={`${id}-name`}>Name</FieldLabel>
                        <Input
                            id={`${id}-name`}
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            maxLength={aeoPromptsTopicsRenameBodyNewTopicMax}
                            autoFocus
                            data-attr="ai-visibility-topic-rename-input"
                        />
                        {topicChangeError ? <FieldError>{topicChangeError}</FieldError> : null}
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={closeTopicDialog}
                        disabledReason={topicChangeSaving ? 'Wait for the topic to save' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => renameTopic(topic, trimmed)}
                        loading={topicChangeSaving}
                        disabledReason={disabledReason}
                        data-attr="ai-visibility-topic-rename-submit"
                    >
                        Rename
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
