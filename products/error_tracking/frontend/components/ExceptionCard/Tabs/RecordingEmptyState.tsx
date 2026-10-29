import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconFilter } from '@posthog/icons'

import { Button, Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from 'lib/ui/quill'

import { exceptionCardLogic } from '../exceptionCardLogic'

export interface RecordingEmptyStateProps {
    title: string
    description?: ReactNode
    children?: ReactNode
}

export function RecordingEmptyState({ title, description, children }: RecordingEmptyStateProps): JSX.Element {
    const { onShowOnlyWithRecording } = useValues(exceptionCardLogic)

    return (
        <Empty className="h-full p-4">
            <EmptyHeader>
                <EmptyTitle>{title}</EmptyTitle>
                {description && <EmptyDescription>{description}</EmptyDescription>}
            </EmptyHeader>
            {(onShowOnlyWithRecording || children) && (
                <EmptyContent>
                    {onShowOnlyWithRecording && (
                        <Button
                            variant="primary"
                            onClick={onShowOnlyWithRecording}
                            data-attr="error-tracking-show-only-with-recording"
                        >
                            <IconFilter />
                            Show only exceptions with a recording
                        </Button>
                    )}
                    {children}
                </EmptyContent>
            )}
        </Empty>
    )
}
