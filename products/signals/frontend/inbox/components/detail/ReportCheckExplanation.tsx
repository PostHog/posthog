import { useId, useLayoutEffect, useRef, useState } from 'react'

import { Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { cn } from 'lib/utils/css-classes'

/** What a check's verdict found, in the agent's Markdown, clamped so one long explanation cannot stretch the rail. */
export function ReportCheckExplanation({ explanation }: { explanation: string }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const [overflowing, setOverflowing] = useState(false)
    const bodyRef = useRef<HTMLDivElement>(null)
    const bodyId = useId()

    useLayoutEffect(() => {
        const element = bodyRef.current
        if (expanded || !element) {
            return
        }
        const checkOverflow = (): void => setOverflowing(element.scrollHeight > element.clientHeight + 1)
        checkOverflow()
        const observer = new ResizeObserver(checkOverflow)
        observer.observe(element)
        return () => observer.disconnect()
    }, [explanation, expanded])

    return (
        <div className="flex flex-col items-start gap-0.5">
            <div ref={bodyRef} id={bodyId} className={cn('w-full', !expanded && 'line-clamp-4')}>
                <LemonMarkdown className="text-xs leading-snug text-secondary" disableImages>
                    {explanation}
                </LemonMarkdown>
            </div>
            {(overflowing || expanded) && (
                <Link
                    className="text-xs"
                    onClick={() => setExpanded(!expanded)}
                    aria-expanded={expanded}
                    aria-controls={bodyId}
                    data-attr="signals-report-check-explanation-toggle"
                >
                    {expanded ? 'Show less' : 'Show more'}
                </Link>
            )}
        </div>
    )
}
