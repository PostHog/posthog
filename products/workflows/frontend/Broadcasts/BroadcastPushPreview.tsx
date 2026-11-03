import { useActions, useValues } from 'kea'

import { IconNotification, IconSend } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { SendTestBroadcastModal } from './SendTestBroadcastModal'

/** The notification as a lock screen shows it, with one audience member's values filled in. */
export function BroadcastPushPreview({ showTestButton = true }: { showTestButton?: boolean }): JSX.Element {
    const { previewPerson, previewPushTitle, previewPushBody } = useValues(broadcastPreviewLogic)
    const { setModalOpen } = useActions(broadcastTestSendLogic)

    return (
        <div className="flex flex-col gap-2" data-attr="broadcast-push-preview">
            {showTestButton ? (
                <div className="flex justify-end">
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconSend />}
                        onClick={() => setModalOpen(true)}
                        data-attr="broadcast-open-test-push"
                    >
                        Send test notification
                    </LemonButton>
                </div>
            ) : null}
            <SendTestBroadcastModal />
            <div className="flex justify-center rounded-lg border border-border bg-surface-secondary px-4 py-6">
                <div className="flex w-full max-w-sm items-start gap-3 rounded-lg border border-border bg-surface-primary p-3 shadow-sm">
                    <span className="flex size-8 shrink-0 items-center justify-center rounded bg-surface-secondary text-lg">
                        <IconNotification />
                    </span>
                    <div className="flex min-w-0 flex-1 flex-col">
                        <div className="flex items-baseline justify-between gap-2">
                            <span className="truncate font-semibold">
                                {previewPushTitle || <span className="text-muted">Notification title</span>}
                            </span>
                            <span className="shrink-0 text-xs text-muted">now</span>
                        </div>
                        {previewPushBody ? (
                            <span className="line-clamp-4 whitespace-pre-wrap wrap-anywhere text-sm">
                                {previewPushBody}
                            </span>
                        ) : null}
                    </div>
                </div>
            </div>
            <span className="text-xs text-muted">
                {previewPerson
                    ? `Values come from ${previewPerson.displayName}. Each device shows the notification in its own style.`
                    : 'No one matches this audience yet, so variables stay unfilled. Each device shows the notification in its own style.'}
            </span>
        </div>
    )
}
