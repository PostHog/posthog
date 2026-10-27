import { cn } from '@posthog/quill'

/** A fixed slot at the row's start, so read and unread rows keep their icons in one column. */
export function NotificationUnreadDot({ unread, className }: { unread: boolean; className?: string }): JSX.Element {
    return (
        <span className={cn('flex w-2 shrink-0 justify-center', className)}>
            {unread && <span role="img" aria-label="Unread" className="size-2 rounded-full bg-primary" />}
        </span>
    )
}
