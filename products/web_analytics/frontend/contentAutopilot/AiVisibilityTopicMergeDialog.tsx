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
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'

export const AiVisibilityTopicMergeDialog = (): JSX.Element => {
    const { topicDialog, topicChangeSaving, topicChangeError, namedTopics } = useValues(aiVisibilityTopicsLogic)
    const { closeTopicDialog, mergeTopics } = useActions(aiVisibilityTopicsLogic)
    const open = topicDialog?.kind === 'merge'
    const topic = open ? topicDialog.topic : ''
    const [target, setTarget] = useState<string | null>(null)
    const id = useId()
    const others = namedTopics.filter((row) => row.topic !== topic)

    useEffect(() => {
        if (open) {
            setTarget(null)
        }
    }, [open, topic])

    return (
        // While the topics merge, the dialog stays open.
        <Credenza open={open} onOpenChange={(next) => !next && !topicChangeSaving && closeTopicDialog()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Merge topic</CredenzaTitle>
                    <CredenzaDescription>
                        {`Every prompt in ${topic} moves to the topic you choose, archived prompts included, and its past answers move with it. ${topic} is then removed, and the topics can't be split again.`}
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody>
                    <Field data-invalid={topicChangeError ? true : undefined}>
                        <FieldLabel htmlFor={`${id}-target`}>Merge into</FieldLabel>
                        <Select<string> value={target} onValueChange={(next) => setTarget(next)}>
                            <SelectTrigger id={`${id}-target`} data-attr="ai-visibility-topic-merge-target">
                                <SelectValue placeholder="Choose a topic" />
                            </SelectTrigger>
                            <SelectContent>
                                {others.map((row) => (
                                    <SelectItem key={row.topic} value={row.topic}>
                                        {`${row.topic} (${pluralize(row.prompts, 'prompt')})`}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        {topicChangeError ? <FieldError>{topicChangeError}</FieldError> : null}
                    </Field>
                </CredenzaBody>
                <CredenzaFooter>
                    <Button
                        variant="outline"
                        onClick={closeTopicDialog}
                        disabledReason={topicChangeSaving ? 'Wait for the topics to merge' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => target && mergeTopics(topic, target)}
                        loading={topicChangeSaving}
                        disabledReason={target ? undefined : 'Choose a topic to merge into'}
                        data-attr="ai-visibility-topic-merge-submit"
                    >
                        Merge
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
