import { useLayoutEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

import { midEllipsis } from 'lib/utils/strings'

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

    return (
        <Tooltip title={display !== text || isClipped ? text : undefined}>
            <span ref={setElement} className={className}>
                {display}
            </span>
        </Tooltip>
    )
}
