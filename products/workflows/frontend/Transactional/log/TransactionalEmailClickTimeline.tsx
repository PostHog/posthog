import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { EmailOutcomeRow } from './emailClicks'
import { TransactionalEmailClickRow } from './TransactionalEmailClickRow'
import { TransactionalEmailEventLink } from './TransactionalEmailEventLink'

const STEP_LABEL = { delivered: 'Delivered', opened: 'Opened' }

export interface TransactionalEmailClickTimelineProps {
    rows: EmailOutcomeRow[] | null
    failed: boolean
    denied: boolean
    onRetry: () => void
    clickTracking: boolean
}

export function TransactionalEmailClickTimeline({
    rows,
    failed,
    denied,
    onRetry,
    clickTracking,
}: TransactionalEmailClickTimelineProps): JSX.Element {
    let content: JSX.Element
    if (rows === null && denied) {
        content = (
            <p className="text-sm text-secondary m-0">
                You need access to persons and to querying events to see each click and the visit it started.
            </p>
        )
    } else if (rows === null && failed) {
        content = (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: onRetry, 'data-attr': 'transactional-email-outcome-retry' }}
            >
                The clicks couldn't load. Check your connection and try again.
            </LemonBanner>
        )
    } else if (rows === null) {
        content = (
            <div className="flex flex-col gap-3">
                {Array.from({ length: 3 }).map((_, index) => (
                    <LemonSkeleton key={index} className="h-5" />
                ))}
            </div>
        )
    } else {
        const clicked = rows.some((row) => row.kind === 'click')
        content = (
            <ol className="list-none m-0 p-0 flex flex-col gap-3">
                {rows.map((row) => (
                    <li key={row.key} className="flex gap-3 min-w-0">
                        <span className="w-24 shrink-0 text-xs text-secondary pt-0.5">
                            <TZLabel time={row.at} formatDate="MMM D" formatTime="HH:mm" />
                        </span>
                        <div className="flex-1 min-w-0">
                            {row.kind === 'click' ? (
                                <TransactionalEmailClickRow row={row} />
                            ) : (
                                <div className="flex items-baseline gap-2">
                                    <span className="text-sm font-semibold">{STEP_LABEL[row.kind]}</span>
                                    <span className="flex-1" />
                                    <TransactionalEmailEventLink uuid={row.eventUuid} at={row.at} />
                                </div>
                            )}
                        </div>
                    </li>
                ))}
                {!clicked && (
                    <li className="text-sm text-secondary">
                        {clickTracking
                            ? 'No clicks yet. Each click shows here with the page it opened.'
                            : 'Click tracking was off for this email, so clicks are not recorded.'}
                    </li>
                )}
            </ol>
        )
    }

    return (
        <section className="ph-no-capture border rounded bg-surface-primary p-4 flex flex-col gap-3">
            <div className="flex flex-col gap-0.5">
                <h3 className="text-base font-semibold m-0">What this email led to</h3>
                <p className="text-xs text-secondary m-0">
                    Each click on the email's links, and the visit it started in your product.
                </p>
            </div>
            {content}
        </section>
    )
}
