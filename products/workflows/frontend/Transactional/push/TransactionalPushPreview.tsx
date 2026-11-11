import { IconNotification } from '@posthog/icons'

/** The notification as a lock screen shows it. Liquid placeholders show as written, because their values come with each send. */
export function TransactionalPushPreview({ title, body }: { title: string; body: string }): JSX.Element {
    return (
        <div
            className="flex justify-center rounded-lg border border-border bg-surface-secondary px-4 py-6"
            data-attr="transactional-push-preview"
        >
            <div className="flex w-full max-w-sm items-start gap-3 rounded-lg border border-border bg-surface-primary p-3 shadow-sm">
                <span className="flex size-8 shrink-0 items-center justify-center rounded bg-surface-secondary text-lg">
                    <IconNotification />
                </span>
                <div className="flex min-w-0 flex-1 flex-col">
                    <div className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-semibold">{title || 'Notification title'}</span>
                        <span className="shrink-0 text-xs text-secondary">now</span>
                    </div>
                    <span className="line-clamp-4 break-words text-sm text-secondary">
                        {body || 'Notification message'}
                    </span>
                </div>
            </div>
        </div>
    )
}
