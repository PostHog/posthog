import { useActions } from 'kea'
import { ReactNode } from 'react'

import { Button, cn } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { NotificationPaneEntry } from './notificationPaneEntries'
import { notificationsPaneLogic } from './notificationsPaneLogic'

interface NotificationRowLinkProps {
    entry: NotificationPaneEntry
    active: boolean
    focusable: boolean
    inOtherProject: boolean
    className?: string
    children: ReactNode
}

/** The row's one target: a link to the item, or a button that marks it read when it has nowhere to go. */
export function NotificationRowLink({
    entry,
    active,
    focusable,
    inOtherProject,
    className,
    children,
}: NotificationRowLinkProps): JSX.Element {
    const { openEntry } = useActions(notificationsPaneLogic)
    return (
        <Button
            size="row"
            left
            nativeButton={!entry.to}
            render={entry.to ? <LinkPrimitive to={entry.to} /> : undefined}
            aria-current={active ? 'page' : undefined}
            tabIndex={focusable ? 0 : -1}
            data-row-primary
            onClick={(event: React.MouseEvent) => {
                if (inOtherProject) {
                    event.preventDefault()
                }
                openEntry(entry, inOtherProject)
            }}
            className={cn('w-full min-w-0 text-left', className)}
        >
            {children}
        </Button>
    )
}
