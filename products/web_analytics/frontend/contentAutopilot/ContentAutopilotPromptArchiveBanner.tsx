import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { Button, Callout, CalloutActions, CalloutContent, CalloutDescription, CalloutIcon } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'

const CONFIRM_TEXT = 'Archive this prompt? It stops running. Its results are kept, and you can restore it.'

export const ContentAutopilotPromptArchiveBanner = (): JSX.Element | null => {
    const { prompt, archiveConfirming, promptArchiving } = useValues(contentAutopilotPromptDetailLogic)
    const { setArchiveConfirming, setPromptArchived } = useActions(contentAutopilotPromptDetailLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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

    if (archiveConfirming && todayRailNav) {
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

    if (archiveConfirming) {
        return (
            <LemonBanner type="warning">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>{CONFIRM_TEXT}</span>
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
