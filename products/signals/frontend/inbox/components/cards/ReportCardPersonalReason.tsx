import { useLayoutEffect, useState } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

/**
 * Why the report sits where it does on the user's Personalized list, clamped to two lines. A clamped
 * reason shows in full in a tooltip on hover. The tooltip does not open on click, so a tap still opens
 * the report. On touch, the ranking pill's hover card holds the full reason.
 */
export function ReportCardPersonalReason({ reason }: { reason: string }): JSX.Element {
    // A callback ref, because setting the tooltip title remounts the paragraph inside the tooltip trigger.
    const [element, setElement] = useState<HTMLParagraphElement | null>(null)
    const [clamped, setClamped] = useState(false)

    useLayoutEffect(() => {
        if (!element) {
            return
        }
        const checkClamped = (): void => setClamped(element.scrollHeight > element.clientHeight + 1)
        checkClamped()
        const observer = new ResizeObserver(checkClamped)
        observer.observe(element)
        return () => observer.disconnect()
    }, [element, reason])

    return (
        <Tooltip title={clamped ? reason : undefined}>
            <p
                ref={setElement}
                className="m-0 min-w-0 line-clamp-2 break-words text-xs leading-snug text-tertiary"
                data-attr="inbox-personal-reason"
            >
                {reason}
            </p>
        </Tooltip>
    )
}
