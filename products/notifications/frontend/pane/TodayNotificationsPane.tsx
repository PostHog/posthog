import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Button, Skeleton, Text } from '@posthog/quill'

import { NotificationsInbox } from './NotificationsInbox'
import { NotificationsPaneEmpty, NotificationsPaneEmptyKind } from './NotificationsPaneEmpty'
import { NotificationsPaneOpenSource, notificationsPaneLogic } from './notificationsPaneLogic'
import { NotificationsProjectSwitchDialog } from './NotificationsProjectSwitchDialog'

const SKELETON_ROWS = 6

function LoadingRows(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 px-2 pt-3" aria-busy aria-label="Loading notifications">
            {Array.from({ length: SKELETON_ROWS }, (_, index) => (
                <div key={index} className="flex gap-2">
                    <Skeleton className="size-4 shrink-0 rounded-sm" />
                    <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                        <Skeleton className="h-3.5 w-3/4" />
                        <Skeleton className="h-2.5 w-1/2" />
                    </div>
                </div>
            ))}
        </div>
    )
}

function emptyKind(showArchived: boolean, filtersActive: boolean): NotificationsPaneEmptyKind {
    if (filtersActive) {
        return 'filtered'
    }
    return showArchived ? 'archived' : 'inbox'
}

export function TodayNotificationsPane({ source }: { source: NotificationsPaneOpenSource }): JSX.Element {
    const { status, entries, nextCursor, showArchived, filtersActive, summary } = useValues(notificationsPaneLogic)
    const { paneOpened, loadNotifications } = useActions(notificationsPaneLogic)

    useEffect(() => {
        paneOpened(source)
    }, [paneOpened, source])

    return (
        <div
            className="TodayPane group/colorful-product-icons colorful-product-icons-true @container/notifications"
            data-quill
        >
            <span className="sr-only" aria-live="polite">
                {summary ? `${summary.direct_count} notifications for you` : ''}
            </span>
            {showArchived && (
                <Text size="xs" variant="muted" className="px-2 pt-1">
                    Archived
                </Text>
            )}
            {status === 'loading' ? (
                <LoadingRows />
            ) : status === 'error' ? (
                <div className="flex items-center justify-between gap-2 px-2 py-3">
                    <Text size="sm" variant="muted">
                        Couldn't load notifications
                    </Text>
                    <Button
                        size="sm"
                        variant="outline"
                        onClick={loadNotifications}
                        data-attr="notifications-pane-retry"
                    >
                        Retry
                    </Button>
                </div>
            ) : entries.length === 0 && !nextCursor ? (
                <NotificationsPaneEmpty kind={emptyKind(showArchived, filtersActive)} />
            ) : (
                <NotificationsInbox />
            )}
            <NotificationsProjectSwitchDialog />
        </div>
    )
}
