import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, toast } from '@posthog/quill'

import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { writeToClipboard } from 'lib/utils/writeToClipboard'

import { NotificationPaneEntry } from './notificationPaneEntries'

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
    if (!entry.to) {
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
                <DropdownMenuItem onClick={() => void copyLink(entry)} data-attr="notification-pane-copy-link">
                    Copy link
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
