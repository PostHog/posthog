import { Fragment } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { Logomark } from 'lib/brand'

// Slack mrkdwn, limited to the two markers our messages actually use.
const MARKUP_SEGMENT = /(\*[^*]+\*|_[^_]+_)/g

function renderSlackMarkup(message: string): JSX.Element[] {
    return message
        .split(MARKUP_SEGMENT)
        .filter(Boolean)
        .map((segment, index) => {
            if (segment.length > 2 && segment.startsWith('*') && segment.endsWith('*')) {
                return <strong key={index}>{segment.slice(1, -1)}</strong>
            }
            if (segment.length > 2 && segment.startsWith('_') && segment.endsWith('_')) {
                return <em key={index}>{segment.slice(1, -1)}</em>
            }
            return <Fragment key={index}>{segment}</Fragment>
        })
}

export interface MCPNotificationPreviewProps {
    /** Slack mrkdwn, as produced by `mcpNotificationPreviewMessage` */
    message: string
    buttonLabel: string
}

/**
 * A Slack-styled render of the message a notification posts, so you can see what lands in the
 * channel before connecting one. Deliberately static: the copy comes from the real template, but
 * the values are samples.
 */
export function MCPNotificationPreview({ message, buttonLabel }: MCPNotificationPreviewProps): JSX.Element {
    return (
        <div className="rounded border bg-surface-primary p-3">
            <div className="flex gap-2">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-surface-secondary">
                    <Logomark size="sm" />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-semibold">PostHog</span>
                        <LemonTag type="muted" size="small">
                            APP
                        </LemonTag>
                        <span className="text-xs text-muted">now</span>
                    </div>
                    <p className="m-0 mt-0.5 break-words text-sm">{renderSlackMarkup(message)}</p>
                    <div className="mt-2">
                        <span className="inline-flex rounded border bg-surface-secondary px-2 py-1 text-xs font-medium">
                            {buttonLabel}
                        </span>
                    </div>
                </div>
            </div>
        </div>
    )
}
