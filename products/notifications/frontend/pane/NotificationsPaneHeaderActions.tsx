import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArchive, IconCheck, IconEllipsis, IconGear } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { NotificationsPaneFilterMenu } from './NotificationsPaneFilterMenu'
import { notificationsPaneLogic } from './notificationsPaneLogic'

const MARK_ALL_READ_LABEL = 'Mark all in this view as read'
const MORE_LABEL = 'More'

export function NotificationsPaneHeaderActions(): JSX.Element {
    const { filters, hasUnread, showArchived } = useValues(notificationsPaneLogic)
    const { setFilters, markAllRead, setShowArchived } = useActions(notificationsPaneLogic)
    return (
        <div className="flex items-center gap-0.5">
            {hasUnread && !showArchived && (
                <Button
                    size="icon"
                    aria-label={MARK_ALL_READ_LABEL}
                    tooltip={MARK_ALL_READ_LABEL}
                    className="text-muted-foreground"
                    onClick={markAllRead}
                    data-attr="notifications-pane-mark-all-read"
                >
                    <IconCheck />
                </Button>
            )}
            <NotificationsPaneFilterMenu filters={filters} onChange={setFilters} />
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            size="icon"
                            aria-label={MORE_LABEL}
                            tooltip={MORE_LABEL}
                            className="text-muted-foreground"
                            data-attr="notifications-pane-more-menu"
                        >
                            <IconEllipsis />
                        </Button>
                    }
                />
                <DropdownMenuContent align="end">
                    <DropdownMenuItem
                        onClick={() => setShowArchived(!showArchived)}
                        data-attr="notifications-pane-show-archived"
                    >
                        <IconArchive />
                        {showArchived ? 'Back to notifications' : 'Archived'}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        onClick={() =>
                            router.actions.push(urls.settings('user-notifications', 'realtime-notifications'))
                        }
                        data-attr="notifications-pane-settings"
                    >
                        <IconGear />
                        Notification settings
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>
        </div>
    )
}
