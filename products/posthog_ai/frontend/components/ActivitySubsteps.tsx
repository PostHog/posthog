import clsx from 'clsx'

import { MarkdownMessage } from '../messages/MarkdownMessage'
import type { ActivityStatus } from './activityTypes'
import { useQuillThread } from './quill/quillThreadContext'

function activitySubstepText(content: string, isInProgress: boolean): string {
    if (content.at(0) === '[' && content.at(-1) === ')') {
        // Skip ... for web search `updates`, where each is a Markdown-formatted link to a search result.
        return content
    }
    if (!content.endsWith('...') && !content.endsWith('\u2026') && !content.endsWith('.') && isInProgress) {
        return content + '...'
    } else if ((content.endsWith('...') || content.endsWith('\u2026')) && !isInProgress) {
        return content.replace(/\u2026/g, '').replace(/[.]/g, '')
    }
    return content
}

export function ActivitySubsteps({
    id,
    substeps,
    status,
}: {
    id: string
    substeps: string[]
    status: ActivityStatus
}): JSX.Element {
    const quill = useQuillThread()
    const isCompleted = status === 'completed'
    const isFailed = status === 'failed'

    return (
        <>
            {substeps.map((substep, substepIndex) => {
                const isCurrentSubstep = substepIndex === substeps.length - 1
                const isCompletedSubstep = substepIndex < substeps.length - 1 || isCompleted

                return (
                    <div key={substepIndex} className="animate-fade-in">
                        <MarkdownMessage
                            id={id}
                            className={clsx(
                                'leading-relaxed',
                                isFailed && 'text-danger',
                                !quill && !isFailed && isCompletedSubstep && 'text-muted',
                                !quill && !isFailed && isCurrentSubstep && !isCompleted && 'text-secondary'
                            )}
                            content={activitySubstepText(substep ?? '', status === 'in_progress')}
                        />
                    </div>
                )
            })}
        </>
    )
}
