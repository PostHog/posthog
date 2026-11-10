import './RunLogSkeleton.scss'

import { memo, useEffect, useState } from 'react'

import {
    ChatBubble,
    ChatBubbleContent,
    ChatMessage,
    ChatMessageContent,
    ChatMessageFooter,
    Skeleton,
    SkeletonText,
} from '@posthog/quill-primitives'

import { cn } from 'lib/utils/css-classes'

import { footerRevealProps } from './quill/footerReveal'
import { ThreadMarker } from './quill/ThreadMarker'

interface SkeletonTurn {
    question: string
    tools: string[]
    paragraphs: number[]
}

const TURNS: SkeletonTurn[] = [{ question: 'w-56', tools: ['w-28'], paragraphs: [3, 2] }]

/** Fades a thread in after a skeleton was on screen, so the swap reads as one change and not as a jump. */
export const RUN_LOG_REVEAL_CLASS = 'RunLogReveal'

// One load can show several skeletons in turn (task, then run log). They share one fade-in clock, so the
// chain waits once and a later skeleton never blinks or restarts the fade.
const FADE_IN_DELAY_MS = 150
let mountedSkeletons = 0
let lastSkeletonHiddenAt = Number.NEGATIVE_INFINITY
let chainStartedAt = 0

function fadeInDelayMs(): number {
    const now = performance.now()
    if (mountedSkeletons === 0 && now - lastSkeletonHiddenAt > 250) {
        chainStartedAt = now
    }
    return FADE_IN_DELAY_MS - (now - chainStartedAt)
}

/**
 * Loading state for "a run/task log is loading" — shared by the runner scene, the lazy `ReadonlyRunSurface`
 * chunk's Suspense fallback, and the `RunSurface` in-stream bootstrap. Built from the quill thread's own
 * parts (`ChatBubble`, `ThreadMarker`, the reserved message footer, `ThreadView`'s 16px row gap), so each turn
 * takes the same space as the turn that replaces it. It shows one turn at the top: a reopened thread lands
 * with its last question at the top (`ThreadView`'s `anchorItemKey`), and a thread shorter than the screen
 * starts at the top too. More guessed turns only add noise. Kept free of the markdown and virtualization
 * chunk, so it is safe as a fallback.
 */
export const RunLogSkeleton = memo(function RunLogSkeleton({
    className,
    listClassName,
    rowClassName,
}: {
    className?: string
    listClassName?: string
    rowClassName?: string
}): JSX.Element {
    const [animationDelay] = useState(() => `${fadeInDelayMs()}ms`)
    useEffect(() => {
        mountedSkeletons++
        return () => {
            mountedSkeletons--
            lastSkeletonHiddenAt = performance.now()
        }
    }, [])
    return (
        <div
            className={cn('RunLogSkeleton flex flex-col h-full min-h-0 w-full overflow-hidden', className)}
            data-attr="run-log-skeleton"
            style={{ animationDelay }}
            role="status"
            aria-busy="true"
        >
            <span className="sr-only">Loading conversation</span>
            <div
                data-quill
                className={cn(
                    'flex flex-col gap-4 w-full max-w-180 mx-auto pt-4 text-[var(--foreground)]',
                    listClassName
                )}
            >
                {TURNS.map((turn, index) => (
                    <div key={index} className="flex flex-col gap-4">
                        <div className={rowClassName}>
                            <ChatMessage align="end">
                                <ChatMessageContent className="gap-1">
                                    <ChatBubble align="end" className="rounded-lg">
                                        <ChatBubbleContent>
                                            <span className="flex items-center h-[1lh] text-sm leading-[1.625]">
                                                <Skeleton className={cn('h-[0.7em] max-w-full', turn.question)} />
                                            </span>
                                        </ChatBubbleContent>
                                    </ChatBubble>
                                    <ChatMessageFooter
                                        {...footerRevealProps(false, undefined, { reserveSpace: true })}
                                    />
                                </ChatMessageContent>
                            </ChatMessage>
                        </div>
                        {turn.tools.map((width, toolIndex) => (
                            <div key={toolIndex} className={rowClassName}>
                                <ThreadMarker icon={<Skeleton className="size-3 rounded-sm" />}>
                                    <span className="flex h-[1lh] items-center">
                                        <Skeleton className={cn('h-2.5', width)} />
                                    </span>
                                </ThreadMarker>
                            </div>
                        ))}
                        <div className={rowClassName}>
                            <ChatMessage align="start" className="w-full">
                                <ChatMessageContent className="w-full gap-1">
                                    <ChatBubble variant="ghost" className="w-full">
                                        <ChatBubbleContent className="flex w-full flex-col gap-3">
                                            {turn.paragraphs.map((lines, paragraphIndex) => (
                                                <SkeletonText
                                                    key={paragraphIndex}
                                                    lines={lines}
                                                    className="text-sm leading-[1.625]"
                                                    maxWidth={paragraphIndex === 0 ? 100 : 90}
                                                />
                                            ))}
                                        </ChatBubbleContent>
                                    </ChatBubble>
                                </ChatMessageContent>
                            </ChatMessage>
                        </div>
                    </div>
                ))}
            </div>
        </div>
    )
})
