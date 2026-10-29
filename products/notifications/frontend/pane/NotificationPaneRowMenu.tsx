import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, toast } from '@posthog/quill'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { NotificationPaneEntry } from './notificationPaneEntries'
import { notificationsPaneLogic } from './notificationsPaneLogic'

const MORE_LABEL = 'More actions'

async function copyLink(entry: NotificationPaneEntry): Promise<void> {
    if (!entry.to) {
        return
    }
    const path = addProjectIdIfMissing(entry.to, entry.notification.team_id ?? undefined)
    const outcome = await writeToClipboard(`${window.location.origin}${path}`)
    if (outcome === 'copied') {
        toast({ title: 'Link copied' })
    } else {
        toast.error({ title: "Couldn't copy the link" })
    }
}

export function NotificationPaneRowMenu({
    entry,
    focusable,
}: {
    entry: NotificationPaneEntry
    focusable: boolean
}): JSX.Element | null {
    const { muteKind } = useActions(notificationsPaneLogic)
    const canMute = entry.notification.team_id !== null
    if (!entry.to && !canMute) {
        return null
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-xs"
                        aria-label={MORE_LABEL}
                        tooltip={MORE_LABEL}
                        tabIndex={focusable ? 0 : -1}
                        data-attr="notification-pane-more"
                    >
                        <IconEllipsis />
                    </Button>
                }
            />
            <DropdownMenuContent align="end">
                {canMute && (
                    <DropdownMenuItem onClick={() => muteKind(entry)} data-attr="notification-pane-mute">
                        Mute this kind in {entry.projectName ?? 'this project'}
                    </DropdownMenuItem>
                )}
                {entry.to && (
                    <DropdownMenuItem onClick={() => void copyLink(entry)} data-attr="notification-pane-copy-link">
                        Copy link
                    </DropdownMenuItem>
                )}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
