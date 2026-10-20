import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { Button, Heading, Text } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import type { MissingSymbolsExampleApi } from '../../../generated/api.schemas'
import { MISSING_SYMBOLS_REASONS, SYMBOL_ID_LABELS } from './missingSymbolsReasons'
import { SourceMapsExampleStackTrace } from './SourceMapsExampleStackTrace'

export function SourceMapsExampleDetail({
    example,
    missingLabel,
    exceptionsLoaded,
    lookbackHours,
    onRetry,
}: {
    example: MissingSymbolsExampleApi
    missingLabel: string
    exceptionsLoaded: boolean
    lookbackHours: number
    onRetry: () => void
}): JSX.Element {
    const reason = MISSING_SYMBOLS_REASONS[example.reason]
    const exception = example.example_exception

    return (
        <div className="flex min-w-0 flex-col gap-3">
            <div className="flex flex-col gap-1">
                <Heading size="sm" render={<h3 className="m-0 break-all font-mono" />}>
                    {example.location ?? 'Unknown file'}
                </Heading>
                {example.symbol_id ? (
                    <Text size="xs" variant="muted" className="break-all" translate="no">
                        {`${SYMBOL_ID_LABELS[example.reason] ?? 'ID'} ${example.symbol_id}`}
                    </Text>
                ) : null}
            </div>
            <div className="flex flex-col gap-1 rounded-md bg-warning p-2">
                <Text size="xs" weight="medium" className="text-warning-foreground">
                    {example.http_status ? `${reason.why} (HTTP ${example.http_status})` : reason.why}
                </Text>
                <Text size="xs">{reason.fix}</Text>
            </div>
            {!exceptionsLoaded ? (
                <Text size="xs" variant="muted">
                    Couldn't load example exceptions.{' '}
                    <Button variant="link" size="inline" onClick={onRetry}>
                        Try again
                    </Button>
                </Text>
            ) : exception ? (
                <div className="flex flex-col gap-1">
                    <Text size="xs" weight="medium">
                        Example exception
                    </Text>
                    <Text size="xs" className="break-words">
                        {[exception.type, exception.value].filter(Boolean).join(': ')}
                    </Text>
                    <SourceMapsExampleStackTrace frames={exception.frames} missingLabel={missingLabel} />
                </div>
            ) : (
                <Text size="xs" variant="muted">
                    {`No exceptions in the last ${lookbackHours} hours had these frames.`}
                </Text>
            )}
            {example.issues.length > 0 ? (
                <div className="flex flex-col gap-1">
                    <Text size="xs" weight="medium">
                        Issues with these frames
                    </Text>
                    {example.issues.map((issue) => (
                        <div key={issue.id} className="flex items-center gap-2">
                            <span className="min-w-0 truncate text-xs">
                                <Button
                                    variant="link"
                                    size="inline"
                                    render={<LinkPrimitive to={urls.errorTrackingIssue(issue.id)} />}
                                    data-attr="error-tracking-source-maps-examples-issue"
                                >
                                    {[issue.name, issue.description].filter(Boolean).join(': ') || 'Untitled issue'}
                                </Button>
                            </span>
                            <Text size="xs" variant="muted" className="ml-auto shrink-0">
                                {pluralize(issue.occurrences, 'occurrence')}
                            </Text>
                        </div>
                    ))}
                </div>
            ) : null}
        </div>
    )
}
