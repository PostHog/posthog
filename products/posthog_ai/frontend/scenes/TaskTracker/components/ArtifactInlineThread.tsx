import { useActions, useValues } from 'kea'
import { CSSProperties, useEffect, useRef } from 'react'

import { cn } from '@posthog/quill-primitives'

import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactCommentThreadCard } from './ArtifactCommentThreadCard'

export const INLINE_THREAD_WIDTH_PX = 320

const KEEP_OPEN_SELECTOR =
    '[data-quill-portal], [data-attr="task-artifact-comment-highlight"], [data-attr="task-artifact-comment-pin-marker"], [data-attr="task-artifact-comments-toggle"]'

export function ArtifactInlineThread({
    logicProps,
    style,
    className,
}: {
    logicProps: TaskArtifactCommentsLogicProps
    style: CSSProperties
    className?: string
}): JSX.Element | null {
    const { activeThreadId, threads } = useValues(taskArtifactCommentsLogic(logicProps))
    const { activateThread } = useActions(taskArtifactCommentsLogic(logicProps))
    const ref = useRef<HTMLDivElement>(null)
    const thread = threads?.find((candidate) => candidate.root.id === activeThreadId) ?? null
    const open = !!thread

    useEffect(() => {
        if (!open) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            if (event.key === 'Escape') {
                activateThread(null)
            }
        }
        const onPointerDown = (event: PointerEvent): void => {
            const target = event.target
            if (target instanceof Element && (ref.current?.contains(target) || target.closest(KEEP_OPEN_SELECTOR))) {
                return
            }
            activateThread(null)
        }
        window.addEventListener('keydown', onKeyDown)
        document.addEventListener('pointerdown', onPointerDown)
        return () => {
            window.removeEventListener('keydown', onKeyDown)
            document.removeEventListener('pointerdown', onPointerDown)
        }
    }, [open, activateThread])

    if (!thread) {
        return null
    }
    return (
        <div
            ref={ref}
            data-quill
            role="dialog"
            aria-label="Comment thread"
            className={cn(
                'absolute z-30 flex max-h-[480px] w-80 max-w-[calc(100%-16px)] flex-col overflow-hidden rounded-lg border border-border bg-background text-left shadow-lg',
                className
            )}
            style={style}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => event.stopPropagation()}
            data-attr="task-artifact-comment-inline-thread"
        >
            <ArtifactCommentThreadCard logicProps={logicProps} thread={thread} inline />
        </div>
    )
}
