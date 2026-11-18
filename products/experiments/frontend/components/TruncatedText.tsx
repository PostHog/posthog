import { useLayoutEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { midEllipsis } from 'lib/utils/strings'

/** The displayed text, and the full text to offer on hover when the display is shortened or clipped. */
export function useTruncatedText(
    text: string,
    maxLength: number
): { display: string; fullText: string | undefined; setElement: (element: HTMLSpanElement | null) => void } {
    // A state ref rather than a ref object: the span remounts when the tooltip wraps it, and the observer must follow.
    const [element, setElement] = useState<HTMLSpanElement | null>(null)
    const [isClipped, setIsClipped] = useState(false)
    const display = midEllipsis(text, maxLength)

    // The caller may cap the width with CSS as well, and a clipped short key still needs its tooltip.
    useLayoutEffect(() => {
        if (!element) {
            return
        }
        const checkClipped = (): void => setIsClipped(element.scrollWidth > element.clientWidth)
        checkClipped()
        const observer = new ResizeObserver(checkClipped)
        observer.observe(element)
        return () => observer.disconnect()
    }, [element, display])

    return { display, fullText: display !== text || isClipped ? text : undefined, setElement }
}

// Keeps the head and tail of an identifier visible, since keys often differ only at the ends.
export function TruncatedText({
    text,
    maxLength,
    className,
}: {
    text: string
    maxLength: number
    className?: string
}): JSX.Element {
    const { display, fullText, setElement } = useTruncatedText(text, maxLength)

    return (
        <Tooltip title={fullText}>
            <span ref={setElement} className={className}>
                {display}
            </span>
        </Tooltip>
    )
}
