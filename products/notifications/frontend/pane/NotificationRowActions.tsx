import { useActions, useValues } from 'kea'

import { IconArchive, IconCheck, IconCircleDashed, IconUndo } from '@posthog/icons'
import { Button, Kbd, cn } from '@posthog/quill'

import { NotificationPaneEntry } from './notificationPaneEntries'
import { NotificationPaneRowMenu } from './NotificationPaneRowMenu'
import { notificationsPaneLogic } from './notificationsPaneLogic'

function ActionTooltip({ label, shortcut }: { label: string; shortcut: string }): JSX.Element {
    return (
        <span className="flex items-center gap-2">
            {label}
            <Kbd>{shortcut}</Kbd>
        </span>
    )
}

interface NotificationRowActionsProps {
    entry: NotificationPaneEntry
    archived: boolean
    visible: boolean
    focusable: boolean
    className?: string
}

/** Read, archive and more, shown on hover or keyboard focus, and always on the open row. */
export function NotificationRowActions({
    entry,
    archived,
    visible,
    focusable,
    className,
}: NotificationRowActionsProps): JSX.Element {
    const { toggleRead, archive, moveToInbox } = useActions(notificationsPaneLogic)
    const { readPendingKeys } = useValues(notificationsPaneLogic)
    const unread = !entry.notification.read
    const readLabel = unread ? 'Mark as read' : 'Mark as unread'
    const archiveLabel = archived ? 'Move to inbox' : entry.count > 1 ? `Archive ${entry.count}` : 'Archive'
    const tabIndex = focusable ? 0 : -1
    return (
        <span
            className={cn(
                'absolute flex items-center gap-0.5',
                !visible && 'opacity-0 group-hover/row:opacity-100 group-focus-within/row:opacity-100',
                className
            )}
        >
            {!archived && (
                <Button
                    size="icon-xs"
                    aria-label={readLabel}
                    tooltip={<ActionTooltip label={readLabel} shortcut="U" />}
                    tabIndex={tabIndex}
                    loading={readPendingKeys.includes(entry.key)}
                    onClick={() => toggleRead(entry)}
                    data-attr="notification-pane-toggle-read"
                >
                    {unread ? <IconCheck /> : <IconCircleDashed />}
                </Button>
            )}
            <Button
                size="icon-xs"
                aria-label={archiveLabel}
                tooltip={<ActionTooltip label={archiveLabel} shortcut="E" />}
                tabIndex={tabIndex}
                onClick={() => (archived ? moveToInbox(entry) : archive(entry))}
                data-attr={archived ? 'notification-pane-unarchive' : 'notification-pane-archive'}
            >
                {archived ? <IconUndo /> : <IconArchive />}
            </Button>
            <NotificationPaneRowMenu entry={entry} focusable={focusable} />
        </span>
    )
}
