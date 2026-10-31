import { IconWarning } from '@posthog/icons'
import { cn } from '@posthog/quill'

import { NotificationPaneEntry } from './notificationPaneEntries'
import { NotificationPaneRowIcon } from './NotificationPaneRowIcon'
import { NotificationRowActions } from './NotificationRowActions'
import { NotificationRowLink } from './NotificationRowLink'
import { NotificationUnreadDot } from './NotificationUnreadDot'

const CRITICAL_PRIORITY = 'critical'
const HIDE_FOR_ACTIONS = 'group-hover/row:hidden group-focus-within/row:hidden'
const MAKE_ROOM_FOR_ACTIONS = 'group-hover/row:pr-17 group-focus-within/row:pr-17'

export interface NotificationRowProps {
    entry: NotificationPaneEntry
    active: boolean
    focusable: boolean
    otherProjectName: string | null
}

function LeadingVisual({ entry }: { entry: NotificationPaneEntry }): JSX.Element {
    if (entry.notification.priority === CRITICAL_PRIORITY) {
        return (
            <span
                aria-label="Critical"
                role="img"
                className="flex size-6 shrink-0 items-center justify-center rounded-full bg-destructive text-destructive-foreground [&_svg]:size-3.5"
            >
                <IconWarning />
            </span>
        )
    }
    return (
        <span className="flex size-6 shrink-0 items-center justify-center">
            <NotificationPaneRowIcon entry={entry} />
        </span>
    )
}

/** An unread item sent to the person, or a critical one: the title and one line of context. */
export function NotificationActionRow({
    entry,
    active,
    focusable,
    otherProjectName,
}: NotificationRowProps): JSX.Element {
    const { notification, context } = entry
    const body = (
        <>
            <NotificationUnreadDot unread={!notification.read} className="self-start pt-2" />
            <LeadingVisual entry={entry} />
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className={cn('flex min-w-0 items-baseline gap-2', active ? 'pr-17' : MAKE_ROOM_FOR_ACTIONS)}>
                    <span className="line-clamp-2 min-w-0 flex-1 font-semibold whitespace-normal">
                        {notification.title}
                    </span>
                    <span
                        className={cn(
                            'shrink-0 text-xs font-normal text-muted-foreground',
                            active ? 'hidden' : HIDE_FOR_ACTIONS
                        )}
                        title={entry.timeTitle}
                    >
                        {entry.timeText}
                    </span>
                </span>
                <span className="truncate text-xs font-normal text-muted-foreground">
                    {context}
                    {otherProjectName && <span> · {otherProjectName}</span>}
                </span>
            </span>
        </>
    )
    return (
        <li
            className={cn(
                'group/row relative flex flex-col rounded-md',
                active ? 'bg-fill-selected' : 'hover:bg-fill-hover'
            )}
            data-attr="notification-action-row"
        >
            <NotificationRowLink
                entry={entry}
                active={active}
                focusable={focusable}
                inOtherProject={otherProjectName !== null}
                className="h-auto items-start gap-2 bg-transparent py-2 pr-2 pl-1 text-foreground hover:bg-transparent"
            >
                {body}
            </NotificationRowLink>
            <NotificationRowActions
                entry={entry}
                archived={false}
                visible={active}
                focusable={focusable}
                className="top-1.5 right-1.5"
            />
        </li>
    )
}
