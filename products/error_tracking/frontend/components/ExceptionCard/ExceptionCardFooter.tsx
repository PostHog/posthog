import { TZLabel } from 'lib/components/TZLabel'
import { Button } from 'lib/ui/quill'
import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { midEllipsis } from 'lib/utils/strings'

export interface ExceptionCardFooterProps {
    eventId?: string
    fingerprint?: string
    label?: JSX.Element
    timestamp?: string
}

export function ExceptionCardFooter({
    eventId,
    fingerprint,
    label,
    timestamp,
}: ExceptionCardFooterProps): JSX.Element | null {
    if (!eventId && !fingerprint && !label && !timestamp) {
        return null
    }

    return (
        <footer className="sticky bottom-0 z-10 flex min-h-9 shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1 border-t bg-surface-primary px-2 py-1 text-xs">
            {label || timestamp ? (
                <div className="flex min-w-0 items-center gap-2">
                    {label}
                    {timestamp ? <TZLabel className="shrink-0 text-muted text-xs" time={timestamp} /> : null}
                </div>
            ) : null}
            {eventId || fingerprint ? (
                <div className="ml-auto flex min-w-0 items-center gap-3">
                    {fingerprint ? (
                        <div className="flex min-w-0 items-center gap-1">
                            <span className="shrink-0 text-secondary">Fingerprint</span>
                            <Button
                                type="button"
                                variant="default"
                                size="xs"
                                aria-label="Copy fingerprint"
                                data-attr="exception-card-copy-fingerprint"
                                onClick={() => void copyToClipboard(fingerprint, 'fingerprint')}
                            >
                                <code className="truncate font-mono" title={fingerprint}>
                                    {midEllipsis(fingerprint, 12)}
                                </code>
                            </Button>
                        </div>
                    ) : null}
                    {eventId ? (
                        <div className="flex min-w-0 items-center gap-1">
                            <span className="shrink-0 text-secondary">Exception ID</span>
                            <Button
                                type="button"
                                variant="default"
                                size="xs"
                                aria-label="Copy exception ID"
                                data-attr="exception-card-copy-id"
                                onClick={() => void copyToClipboard(eventId, 'exception ID')}
                            >
                                <code className="truncate font-mono" title={eventId}>
                                    {midEllipsis(eventId, 12)}
                                </code>
                            </Button>
                        </div>
                    ) : null}
                </div>
            ) : null}
        </footer>
    )
}
