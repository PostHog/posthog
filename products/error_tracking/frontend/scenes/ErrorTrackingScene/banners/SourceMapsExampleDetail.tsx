import { Button, Text } from 'lib/ui/quill'

import type { MissingSymbolsExampleApi } from '../../../generated/api.schemas'
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
            <Text size="xs" weight="medium">
                Example exception
            </Text>
            <Text size="xs" className="break-words">
                {[exception.type, exception.value].filter(Boolean).join(': ')}
            </Text>
            <SourceMapsExampleStackTrace frames={exception.frames} missingLabel={missingLabel} />
        </div>
    )
}
