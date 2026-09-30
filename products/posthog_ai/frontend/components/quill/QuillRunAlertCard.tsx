import { IconCopy, IconWarning } from '@posthog/icons'
import { Button, Card, CardContent, CardFooter, CardHeader, CardTitle } from '@posthog/quill-primitives'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { MarkdownMessage } from '../../messages/MarkdownMessage'
import type { RunAlertKind } from '../../types/streamTypes'
import { RUN_ALERT_TITLES } from '../runAlertTitles'
import { QuillFooterButton } from './QuillFooterButton'

export interface QuillRunAlertCardProps {
    kind: RunAlertKind
    id: string
    message?: string
    retryable?: boolean
    onRetry?: () => void
    undeliveredMessage?: boolean
    copyDetails?: string
}

export function QuillRunAlertCard({
    kind,
    id,
    message,
    retryable,
    onRetry,
    undeliveredMessage,
    copyDetails,
}: QuillRunAlertCardProps): JSX.Element {
    const canRetry = kind === 'connection_failed' && retryable && onRetry
    return (
        <Card size="sm" className="max-w-4/5" data-attr="run-alert-card">
            <CardHeader className="flex-row items-center gap-2">
                <IconWarning className="size-4 shrink-0 text-destructive-foreground" />
                <CardTitle className="grow">{RUN_ALERT_TITLES[kind]}</CardTitle>
                {copyDetails && (
                    <QuillFooterButton
                        label="Copy run details for support"
                        dataAttr="run-error-copy-details"
                        onClick={() => void copyToClipboard(copyDetails, 'run details')}
                    >
                        <IconCopy />
                    </QuillFooterButton>
                )}
            </CardHeader>
            {(message || undeliveredMessage) && (
                <CardContent className="flex min-w-0 flex-col gap-1 break-words text-foreground">
                    {message && <MarkdownMessage content={message} id={`${id}-message`} />}
                    {undeliveredMessage && kind !== 'message_undelivered' && (
                        <div>Your last message was not delivered.</div>
                    )}
                </CardContent>
            )}
            {canRetry && (
                <CardFooter>
                    <Button variant="outline" size="sm" onClick={onRetry} data-attr="agent-stream-retry">
                        Retry
                    </Button>
                </CardFooter>
            )}
        </Card>
    )
}
