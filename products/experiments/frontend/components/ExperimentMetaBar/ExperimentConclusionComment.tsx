import { useLayoutEffect, useRef, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export function ExperimentConclusionComment({ comment }: { comment: string }): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const [isOverflowing, setIsOverflowing] = useState(false)
    const textRef = useRef<HTMLParagraphElement>(null)

    useLayoutEffect(() => {
        if (isExpanded) {
            return
        }
        const element = textRef.current
        if (!element) {
            return
        }
        const checkOverflow = (): void => setIsOverflowing(element.scrollHeight > element.clientHeight + 1)
        checkOverflow()
        const observer = new ResizeObserver(checkOverflow)
        observer.observe(element)
        return () => observer.disconnect()
    }, [comment, isExpanded])

    return (
        <>
            <p
                ref={textRef}
                id="experiment-conclusion-comment-text"
                className={cn(
                    'metric-cell font-normal m-0 mt-1 leading-relaxed whitespace-pre-wrap break-words',
                    !isExpanded && 'max-h-36 overflow-hidden'
                )}
            >
                {comment}
            </p>
            {(isOverflowing || isExpanded) && (
                <LemonButton
                    className="mt-1"
                    size="xsmall"
                    type="tertiary"
                    data-attr="experiment-conclusion-toggle"
                    aria-expanded={isExpanded}
                    aria-controls="experiment-conclusion-comment-text"
                    onClick={() => setIsExpanded(!isExpanded)}
                >
                    {isExpanded ? 'Show less' : 'Show more'}
                </LemonButton>
            )}
        </>
    )
}
