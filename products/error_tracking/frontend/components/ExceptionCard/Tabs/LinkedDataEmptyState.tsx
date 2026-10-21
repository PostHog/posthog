import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from 'lib/ui/quill'

import type { ErrorTrackingLinkedDataKind } from '~/queries/schema/schema-general'

import { exceptionCardLogic } from '../exceptionCardLogic'

const FILTER_LABELS: Record<ErrorTrackingLinkedDataKind, string> = {
    logs: 'Show only exceptions with logs',
    recording: 'Show only exceptions with a recording',
}

export interface LinkedDataEmptyStateProps {
    kind: ErrorTrackingLinkedDataKind
    title: string
    description?: ReactNode
    children?: ReactNode
}

export function LinkedDataEmptyState({ kind, title, description, children }: LinkedDataEmptyStateProps): JSX.Element {
    const { linkedData } = useValues(exceptionCardLogic)

    return (
        <Empty className="h-full p-4">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                {description && <EmptyDescription>{description}</EmptyDescription>}
            </EmptyHeader>
            {(linkedData || children) && (
                <EmptyContent>
                    {linkedData && (
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
