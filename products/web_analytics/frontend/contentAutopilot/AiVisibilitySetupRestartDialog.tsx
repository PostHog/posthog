import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    Button,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { contentAutopilotSetupLogic } from './contentAutopilotSetupLogic'

/** Confirms starting setup again, which removes what the last setup saved. */
export const AiVisibilitySetupRestartDialog = ({
    open,
    onOpenChange,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
}): JSX.Element => {
    const { setupContext } = useValues(contentAutopilotSetupLogic)
    const { startAgain } = useActions(contentAutopilotSetupLogic)
    const prompts = (setupContext?.active_prompts ?? 0) + (setupContext?.paused_prompts ?? 0)
    const keywords = setupContext?.keywords ?? 0
    const site = setupContext?.own_domains[0]

    return (
        <AlertDialog open={open} onOpenChange={onOpenChange}>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Start again with another website?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {prompts + keywords > 0
                            ? `This removes the ${pluralize(prompts, 'prompt')} and ${pluralize(keywords, 'keyword')} PostHog set up${site ? ` for ${site}` : ''}, so it can set up your site again from scratch.`
                            : `PostHog sets up your site again from scratch${site ? `, starting from ${site}` : ''}.`}{' '}
                        Answers already collected stay in your history, and engine settings don't change.
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose
                        render={<Button variant="destructive-outline" />}
                        onClick={startAgain}
                        data-attr="ai-visibility-setup-restart-confirm"
                    >
                        Start again
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
