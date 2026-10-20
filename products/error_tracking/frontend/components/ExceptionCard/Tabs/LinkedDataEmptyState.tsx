import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import { type LinkedDataKind, exceptionCardLogic } from '../exceptionCardLogic'

const FILTER_LABELS: Record<LinkedDataKind, string> = {
    logs: 'Show only exceptions with logs',
    recording: 'Show only exceptions with a recording',
}

const LINKED_DATA_NOUNS: Record<LinkedDataKind, string> = {
    logs: 'linked logs',
    recording: 'a recording',
}

export interface LinkedDataEmptyStateProps {
    kind: LinkedDataKind
    title: string
    description?: ReactNode
    children?: ReactNode
}

export function LinkedDataEmptyState({ kind, title, description, children }: LinkedDataEmptyStateProps): JSX.Element {
    const { linkedData } = useValues(exceptionCardLogic)
    const linkedCount = linkedData?.exceptionCounts?.[kind] ?? 0

    return (
        <Empty className="h-full p-4">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                {description && <EmptyDescription>{description}</EmptyDescription>}
                {linkedData && linkedCount > 0 && (
                    <EmptyDescription>
                        {pluralize(linkedCount, 'exception')} in this issue {linkedCount === 1 ? 'has' : 'have'}{' '}
                        {LINKED_DATA_NOUNS[kind]} in the selected date range.
                    </EmptyDescription>
                )}
            </EmptyHeader>
            {((linkedData && linkedCount > 0) || children) && (
                <EmptyContent>
                    {linkedData && linkedCount > 0 && (
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
