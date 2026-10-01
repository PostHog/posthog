import { IconChat, IconCloud, IconPinFilled, IconSpinner } from '@posthog/icons'
import { cn } from '@posthog/quill'

import { TodaySessionIconKind, todaySessionIcon } from '~/layout/today/todaySessionIcon'
import { TodayWorkItem } from '~/layout/today/todayWorkItems'

// A settled run fills its cloud, like PostHog Desktop's feed cards. `IconCloud` is an outline path, so
// `*:fill-current` fills that path with the text colour.
const ICONS: Record<TodaySessionIconKind, { label: string; icon: JSX.Element }> = {
    chat: { label: 'Chat', icon: <IconChat className="text-muted-foreground" /> },
    running: { label: 'Running', icon: <IconSpinner className="text-info-foreground motion-safe:animate-spin" /> },
    queued: { label: 'Queued', icon: <IconCloud className="text-muted-foreground motion-safe:animate-pulse" /> },
    completed: { label: 'Completed', icon: <IconCloud className="text-success-foreground *:fill-current" /> },
    failed: { label: 'Failed', icon: <IconCloud className="text-destructive-foreground *:fill-current" /> },
    stopped: { label: 'Stopped', icon: <IconCloud className="text-muted-foreground *:fill-current" /> },
    pinned: { label: 'Pinned', icon: <IconPinFilled className="text-foreground" /> },
    session: { label: 'Session', icon: <IconCloud className="text-muted-foreground" /> },
}

export function SpaceFeedStatusIcon({ item, className }: { item: TodayWorkItem; className?: string }): JSX.Element {
    const { label, icon } = ICONS[todaySessionIcon(item, false)]
    return (
        <span
            role="img"
            aria-label={label}
            className={cn('flex size-3.5 shrink-0 items-center justify-center', className)}
        >
            {icon}
        </span>
    )
}
