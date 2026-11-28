import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
    Text,
} from '@posthog/quill'

import { aiVisibilityTopicsLogic } from './aiVisibilityTopicsLogic'

export const AiVisibilityTopicRemoveDialog = (): JSX.Element => {
    const { topicDialog, topicChangeSaving, topicChangeError } = useValues(aiVisibilityTopicsLogic)
    const { closeTopicDialog, removeTopic } = useActions(aiVisibilityTopicsLogic)
    const open = topicDialog?.kind === 'remove'
    const topic = open ? topicDialog.topic : ''

    return (
        <AlertDialog open={open} onOpenChange={(next) => !next && !topicChangeSaving && closeTopicDialog()}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Remove {topic}?</AlertDialogTitle>
                    <AlertDialogDescription>
                        Every prompt in this topic is kept and gets no topic, archived prompts included. Its past
                        answers move to No topic as well.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                {topicChangeError ? (
                    <Text size="xs" className="m-0 text-destructive-foreground">
                        {topicChangeError}
                    </Text>
                ) : null}
                <AlertDialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeTopicDialog}
                        disabledReason={topicChangeSaving ? 'Wait for the topic to be removed' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive-outline"
                        onClick={() => removeTopic(topic)}
                        loading={topicChangeSaving}
                        data-attr="ai-visibility-topic-remove-confirm"
                    >
                        Remove topic
                    </Button>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
