import { useActions } from 'kea'

import { IconArchive, IconBell, IconFilter } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    IconStack,
    IconStackItem,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { notificationsPaneLogic } from './notificationsPaneLogic'

export type NotificationsPaneEmptyKind = 'inbox' | 'archived' | 'filtered'

const EMPTY_COPY: Record<NotificationsPaneEmptyKind, { title: string; icon: JSX.Element }> = {
    inbox: { title: 'No notifications yet', icon: <IconBell /> },
    archived: { title: 'Nothing archived', icon: <IconArchive /> },
    filtered: { title: 'No notifications match these filters', icon: <IconFilter /> },
}

export function NotificationsPaneEmpty({ kind }: { kind: NotificationsPaneEmptyKind }): JSX.Element {
    const { clearFilters } = useActions(notificationsPaneLogic)
    const { title, icon } = EMPTY_COPY[kind]
    return (
        <Empty className="mt-3 flex-none py-8">
            <EmptyHeader>
                <EmptyMedia>
                    <IconStack>
                        <IconStackItem>{icon}</IconStackItem>
                    </IconStack>
                </EmptyMedia>
                <EmptyTitle className="text-center">{title}</EmptyTitle>
            </EmptyHeader>
            {kind === 'filtered' ? (
                <EmptyContent>
                    <Button variant="outline" onClick={clearFilters} data-attr="notifications-pane-empty-clear-filters">
                        Clear filters
                    </Button>
                </EmptyContent>
            ) : kind === 'inbox' ? (
                <EmptyContent>
                    <Button
                        variant="outline"
                        nativeButton={false}
                        render={<LinkPrimitive to={urls.settings('user-notifications', 'realtime-notifications')} />}
                        data-attr="notifications-pane-empty-settings"
                    >
                        Notification settings
                    </Button>
                </EmptyContent>
            ) : null}
        </Empty>
    )
}
