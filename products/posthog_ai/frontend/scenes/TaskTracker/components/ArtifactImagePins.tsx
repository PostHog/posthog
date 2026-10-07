import { useActions, useValues } from 'kea'
import { CSSProperties, useEffect, useRef } from 'react'

import { cn } from '@posthog/quill-primitives'

import { fullNameOrEmail } from 'lib/utils/strings'

import type { RegionCommentAnchor } from '../artifactComments'
import { TaskArtifactCommentsLogicProps, taskArtifactCommentsLogic } from '../taskArtifactCommentsLogic'
import { ArtifactInlineThread } from './ArtifactInlineThread'
import { ArtifactPendingComment } from './ArtifactPendingComment'

/** The point of a pin sits on its region's bottom left corner, the same spot Desktop draws it on. */
function pinStyle(anchor: RegionCommentAnchor): { left: string; top: string } {
    return { left: `${anchor.x * 100}%`, top: `${(anchor.y + anchor.height) * 100}%` }
}

function besidePinStyle(region: RegionCommentAnchor): CSSProperties {
    return {
        ...(region.y < 0.5
            ? { top: `${(region.y + region.height) * 100}%` }
            : { bottom: `${(1 - region.y - region.height) * 100}%` }),
        ...(region.x < 0.5 ? { left: `${region.x * 100}%` } : { right: `${(1 - region.x - region.width) * 100}%` }),
    }
}

function besidePinClassName(region: RegionCommentAnchor): string {
    return cn('pointer-events-auto', region.y < 0.5 ? 'mt-1' : 'mb-8')
}

function PinMarker({
    label,
    number,
    active,
    onClick,
    anchor,
    threadId,
}: {
    threadId?: string
    label: string
    number: number | null
    active: boolean
    onClick?: () => void
    anchor: RegionCommentAnchor
}): JSX.Element {
    return (
        <button
            type="button"
            aria-label={label}
            aria-pressed={onClick ? active : undefined}
            // A square bottom left corner makes the teardrop, and that corner is the spot the pin marks.
            className={cn(
                'absolute z-20 flex size-6 -translate-y-full items-center justify-center rounded-full rounded-bl-none bg-background text-xs font-semibold text-foreground shadow-md tabular-nums',
                active ? 'ring-2 ring-ring' : 'ring-1 ring-foreground/20',
                onClick ? 'pointer-events-auto cursor-pointer' : 'pointer-events-none'
            )}
            // Pins sit at stored shares of the image size, which utility classes cannot express.
            style={pinStyle(anchor)}
            onClick={onClick}
            data-thread-id={threadId}
            data-attr="task-artifact-comment-pin-marker"
        >
            {number ?? '+'}
        </button>
    )
}

/** Comment pins on an image, and the box for a new pin. Renders inside the image viewer's overlay. */
export function ArtifactImagePins({ logicProps }: { logicProps: TaskArtifactCommentsLogicProps }): JSX.Element {
    const { anchoredThreads, activeThreadId, pendingAnchor } = useValues(taskArtifactCommentsLogic(logicProps))
    const { activateThread } = useActions(taskArtifactCommentsLogic(logicProps))
    const rootRef = useRef<HTMLDivElement>(null)

    // A pick in the comments menu scrolls its pin into view when the image is zoomed in.
    useEffect(() => {
        if (activeThreadId) {
            rootRef.current
                ?.querySelector<HTMLElement>(`[data-thread-id="${CSS.escape(activeThreadId)}"]`)
                ?.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
        }
    }, [activeThreadId])

    const pendingRegion = pendingAnchor?.kind === 'region' ? pendingAnchor : null
    const activeAnchor = anchoredThreads.find((thread) => thread.root.id === activeThreadId)?.anchor
    const activeRegion = activeAnchor?.kind === 'region' ? activeAnchor : null
    return (
        <div ref={rootRef} className="pointer-events-none absolute inset-0">
            {anchoredThreads.map((thread) => {
                if (thread.anchor?.kind !== 'region') {
                    return null
                }
                const author = thread.root.created_by ? fullNameOrEmail(thread.root.created_by) : 'Deleted user'
                return (
                    <PinMarker
                        key={thread.root.id}
                        threadId={thread.root.id}
                        label={`Open pin ${thread.pinNumber} from ${author}`}
                        number={thread.pinNumber}
                        active={thread.root.id === activeThreadId}
                        onClick={() => activateThread(thread.root.id)}
                        anchor={thread.anchor}
                    />
                )
            })}
            {pendingRegion && (
                <>
                    <PinMarker label="New pin" number={null} active anchor={pendingRegion} />
                    <ArtifactPendingComment
                        logicProps={logicProps}
                        className={besidePinClassName(pendingRegion)}
                        // The box opens toward the middle of the image, so it stays on the image as far as it can.
                        style={besidePinStyle(pendingRegion)}
                    />
                </>
            )}
            {activeRegion && !pendingRegion && (
                <ArtifactInlineThread
                    logicProps={logicProps}
                    className={besidePinClassName(activeRegion)}
                    style={besidePinStyle(activeRegion)}
                />
            )}
        </div>
    )
}
