import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import type { ErrorTrackingLinkedDataKind } from '~/queries/schema/schema-general'

import { exceptionCardLogic } from '../exceptionCardLogic'

const FILTER_LABELS: Record<ErrorTrackingLinkedDataKind, string> = {
    logs: 'Show only exceptions with logs',
    recording: 'Show only exceptions with a recording',
}

const LINKED_DATA_NOUNS: Record<ErrorTrackingLinkedDataKind, string> = {
    logs: 'linked logs',
    recording: 'a recording',
}

export interface LinkedDataEmptyStateProps {
    kind: ErrorTrackingLinkedDataKind
    title: string
    description?: ReactNode
    children?: ReactNode
}

export function LinkedDataEmptyState({ kind, title, description, children }: LinkedDataEmptyStateProps): JSX.Element {
    const { linkedData } = useValues(exceptionCardLogic)
    const linkedCount = linkedData?.exceptionCounts?.[kind] ?? null
    // An incomplete count of 0 only covers the most recent exceptions, so older ones can still match.
    const canFilter = !!linkedData && !!linkedCount && (linkedCount.count > 0 || !linkedCount.complete)

    return (
        <Empty className="h-full p-4">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                {description && <EmptyDescription>{description}</EmptyDescription>}
                {linkedCount && linkedCount.count > 0 && (
                    <EmptyDescription>
                        {linkedCount.complete ? '' : 'At least '}
                        {pluralize(linkedCount.count, 'exception')} in this issue{' '}
                        {linkedCount.count === 1 ? 'has' : 'have'} {LINKED_DATA_NOUNS[kind]} in the selected date range.
                    </EmptyDescription>
                )}
            </EmptyHeader>
            {(canFilter || children) && (
                <EmptyContent>
                    {canFilter && linkedData && (
                        <Button
                            variant="primary"
                            onClick={() => linkedData.showOnlyExceptionsWith(kind)}
                            data-attr={`error-tracking-show-only-with-${kind}`}
                        >
                            <IconFilter />
                            {FILTER_LABELS[kind]}
                        </Button>
                    )}
                    {children}
                </EmptyContent>
            )}
        </Empty>
    )
}
