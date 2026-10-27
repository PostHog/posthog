import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

export const ContentAutopilotPromptArchiveBanner = (): JSX.Element | null => {
    const { prompt, archiveConfirming, promptArchiving } = useValues(contentAutopilotPromptDetailLogic)
    const { setArchiveConfirming, setPromptArchived } = useActions(contentAutopilotPromptDetailLogic)

    if (prompt?.archived_at) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Restore',
                    onClick: () => setPromptArchived(false),
                    loading: promptArchiving,
                    'data-attr': 'content-autopilot-prompt-restore',
                }}
            >
                This prompt is archived and doesn't run. A restored prompt stays off until you turn it on.
            </LemonBanner>
        )
    }

    if (archiveConfirming) {
        return (
            <LemonBanner type="warning">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>Archive this prompt? It stops running. Its results are kept, and you can restore it.</span>
                    <div className="flex gap-2">
                        <LemonButton
                            size="small"
                            type="secondary"
                            onClick={() => setArchiveConfirming(false)}
                            disabledReason={promptArchiving ? 'Archiving the prompt' : undefined}
                            data-attr="content-autopilot-prompt-archive-cancel"
                        >
                            Cancel
                        </LemonButton>
                        <LemonButton
                            size="small"
                            type="primary"
                            status="danger"
                            onClick={() => setPromptArchived(true)}
                            loading={promptArchiving}
                            data-attr="content-autopilot-prompt-archive-confirm"
                        >
                            Archive prompt
                        </LemonButton>
                    </div>
                </div>
            </LemonBanner>
        )
    }

    return null
}
