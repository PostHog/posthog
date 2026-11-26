import { useActions, useValues } from 'kea'

import { Button, Callout, CalloutActions, CalloutContent, CalloutDescription, CalloutIcon } from '@posthog/quill'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

const CONFIRM_TEXT = 'Archive this prompt? It stops running. Its results are kept, and you can restore it.'

export const ContentAutopilotPromptArchiveBanner = (): JSX.Element | null => {
    const { prompt, archiveConfirming, promptArchiving } = useValues(contentAutopilotPromptDetailLogic)
    const { setArchiveConfirming, setPromptArchived } = useActions(contentAutopilotPromptDetailLogic)

    if (prompt?.archived_at) {
        return (
            <AiVisibilityBanner
                type="info"
                action={{
                    children: 'Restore',
                    onClick: () => setPromptArchived(false),
                    loading: promptArchiving,
                    'data-attr': 'content-autopilot-prompt-restore',
                }}
            >
                This prompt is archived and doesn't run. A restored prompt stays off until you turn it on.
            </AiVisibilityBanner>
        )
    }

    if (archiveConfirming) {
        return (
            <Callout tone="warning">
                <CalloutIcon />
                <CalloutContent>
                    <CalloutDescription>{CONFIRM_TEXT}</CalloutDescription>
                </CalloutContent>
                <CalloutActions>
                    <Button
                        variant="outline"
                        onClick={() => setArchiveConfirming(false)}
                        disabledReason={promptArchiving ? 'Archiving the prompt' : undefined}
                        data-attr="content-autopilot-prompt-archive-cancel"
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="destructive"
                        onClick={() => setPromptArchived(true)}
                        loading={promptArchiving}
                        data-attr="content-autopilot-prompt-archive-confirm"
                    >
                        Archive prompt
                    </Button>
                </CalloutActions>
            </Callout>
        )
    }

    return null
}
