import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, Text } from 'lib/ui/quill'
import { urls } from 'scenes/urls'

import type { MissingSymbolsExampleApi } from '../../../generated/api.schemas'
import { SourceMapsExampleStackTrace } from './SourceMapsExampleStackTrace'

export function SourceMapsExampleDetail({
    example,
    missingLabel,
    exceptionsLoaded,
    lookbackHours,
    onRetry,
    onOpenException,
}: {
    example: MissingSymbolsExampleApi
    missingLabel: string
    exceptionsLoaded: boolean
    lookbackHours: number
    onRetry: () => void
    onOpenException: () => void
}): JSX.Element {
    const exception = example.example_exception

    if (!exceptionsLoaded) {
        return (
            <Text size="xs" variant="muted">
                Couldn't load example exceptions.{' '}
                <Button variant="link" size="inline" onClick={onRetry}>
                    Try again
                </Button>
            </Text>
        )
    }

    if (!exception) {
        return (
            <Text size="xs" variant="muted">
                {`No exceptions in the last ${lookbackHours} hours had these frames.`}
            </Text>
        )
    }

    return (
        <div className="flex min-w-0 flex-col gap-1">
            <div className="flex items-center gap-2">
                <Text size="xs" weight="medium" className="flex-1">
                    Example exception
                </Text>
                {exception.issue_id ? (
                    <Button
                        variant="outline"
                        render={
                            <LinkPrimitive
                                to={urls.errorTrackingIssue(exception.issue_id, {
                                    fingerprint: exception.fingerprint,
                                    timestamp: exception.timestamp,
                                })}
                            />
                        }
                        onClick={onOpenException}
                        data-attr="error-tracking-source-maps-examples-open-exception"
                    >
                        Open exception
                    </Button>
                ) : null}
            </div>
            <Text size="xs" className="break-words">
                {[exception.type, exception.value].filter(Boolean).join(': ')}
            </Text>
            <SourceMapsExampleStackTrace frames={exception.frames} missingLabel={missingLabel} />
        </div>
    )
}
