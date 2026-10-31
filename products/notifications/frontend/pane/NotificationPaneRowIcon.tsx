import { IconBell, IconComment, IconDatabase, IconPulse, IconWarning } from '@posthog/icons'
import { Avatar, AvatarFallback } from '@posthog/quill'

import { getIconColor, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { NotificationCategory, isPersonalNotification, notificationCategory } from './notificationKinds'
import { NotificationPaneEntry } from './notificationPaneEntries'

const CATEGORY_ICONS: Record<NotificationCategory, JSX.Element> = {
    mentions: <IconComment />,
    approvals: <IconComment />,
    alerts: <IconWarning />,
    pipelines: <IconDatabase />,
    other: <IconBell />,
}

const UNCOLORED = 'currentColor'

function actorName(entry: NotificationPaneEntry): string | null {
    const actor = entry.notification.metadata?.actor_name
    return typeof actor === 'string' ? actor : null
}

function initials(name: string): string {
    return name
        .split(/\s+/)
        .slice(0, 2)
        .map((part) => part[0]?.toUpperCase() ?? '')
        .join('')
}

export function NotificationPaneRowIcon({ entry }: { entry: NotificationPaneEntry }): JSX.Element {
    const { notification_type, resource_type } = entry.notification
    const actor = actorName(entry)
    if (isPersonalNotification(notification_type) && actor) {
        return (
            <Avatar size="xs" className="shrink-0" aria-hidden>
                <AvatarFallback className="bg-foreground/10">{initials(actor)}</AvatarFallback>
            </Avatar>
        )
    }
    const productIcon =
        resource_type && getIconColor(resource_type)[0] !== UNCOLORED
            ? iconForType(resource_type as FileSystemIconType)
            : null
    return (
        <span
            aria-hidden
            className="mt-0.5 flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-4"
            data-keep-color
        >
            {productIcon ??
                (notification_type === 'web_analytics_digest' ? (
                    <IconPulse />
                ) : (
                    CATEGORY_ICONS[notificationCategory(notification_type)]
                ))}
        </span>
    )
}
