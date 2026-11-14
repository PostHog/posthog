import { cn } from '@posthog/quill'

import { NotificationRowProps } from './NotificationActionRow'
import { NotificationPaneRowIcon } from './NotificationPaneRowIcon'
import { NotificationRowActions } from './NotificationRowActions'
import { NotificationRowLink } from './NotificationRowLink'
import { NotificationUnreadDot } from './NotificationUnreadDot'

const HIDE_FOR_ACTIONS = 'group-hover/row:hidden group-focus-within/row:hidden'
const MAKE_ROOM_FOR_ACTIONS = 'group-hover/row:pr-17 group-focus-within/row:pr-17'

interface NotificationCompactRowProps extends NotificationRowProps {
    archived: boolean
}

/** An update the person may want to know about: one line, quiet once read. */
export function NotificationCompactRow({
    entry,
    active,
    focusable,
    archived,
    otherProjectName,
}: NotificationCompactRowProps): JSX.Element {
    const { notification, count } = entry
    const unread = !notification.read
    const body = (
        <>
            <NotificationUnreadDot unread={unread} />
            <NotificationPaneRowIcon entry={entry} />
            <span
                className={cn(
                    'min-w-0 flex-1 truncate',
                    unread ? 'font-medium text-foreground' : 'font-normal text-muted-foreground'
                )}
            >
                {notification.title}
            </span>
            <span
                className={cn(
                    'flex shrink-0 items-center gap-2 text-xs font-normal text-muted-foreground',
                    active ? 'hidden' : HIDE_FOR_ACTIONS
                )}
            >
                {count > 1 && <span>×{count}</span>}
                {otherProjectName && <span className="max-w-20 truncate">{otherProjectName}</span>}
                <span title={entry.timeTitle}>{entry.timeText}</span>
            </span>
        </>
    )
    return (
        <li className="group/row relative flex min-w-0" data-attr="notification-compact-row">
            <NotificationRowLink
                entry={entry}
                active={active}
                focusable={focusable}
                inOtherProject={otherProjectName !== null}
                className={cn('gap-2 pr-2 pl-1', active ? 'bg-fill-selected pr-17' : MAKE_ROOM_FOR_ACTIONS)}
            >
                {body}
            </NotificationRowLink>
            <NotificationRowActions
                entry={entry}
                archived={archived}
                visible={active}
                focusable={focusable}
                className="top-1/2 right-1 -translate-y-1/2"
            />
        </li>
    )
}
