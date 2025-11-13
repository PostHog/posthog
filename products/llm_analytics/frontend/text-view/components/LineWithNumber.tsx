/**
 * Line rendering component with line number and permalink functionality
 * Uses ref for proper scroll handling
 */
import { useEffect, useRef } from 'react'

import { Tooltip } from '@posthog/lemon-ui'

interface LineWithNumberProps {
    lineNumber: number
    content: string
    isActive: boolean
    padding: number
    onCopyPermalink?: (lineNumber: number) => void
}

export function LineWithNumber({
    lineNumber,
    content,
    isActive,
    padding,
    onCopyPermalink,
}: LineWithNumberProps): JSX.Element {
    const lineRef = useRef<HTMLSpanElement>(null)

    useEffect(() => {
        if (isActive && lineRef.current) {
            lineRef.current.scrollIntoView({ behavior: 'smooth', block: 'center' })
            lineRef.current.classList.add('bg-warning-highlight', 'border-l-4', 'border-warning')
            const timer = setTimeout(() => {
                lineRef.current?.classList.remove('bg-warning-highlight', 'border-l-4', 'border-warning')
            }, 3000)
            return () => clearTimeout(timer)
        }
    }, [isActive])

    const handleCopyPermalink = (): void => {
        if (onCopyPermalink) {
            onCopyPermalink(lineNumber)
        }
    }

    const paddedLineNumber = padding > 0 ? lineNumber.toString().padStart(padding, '0') : lineNumber.toString()

    return (
        <span ref={lineRef}>
            <Tooltip title="Click to copy permalink to this line">
                <button
                    type="button"
                    className="text-muted hover:text-link cursor-pointer"
                    onClick={handleCopyPermalink}
                >
                    L{paddedLineNumber}:
                </button>
            </Tooltip>
            {content}
        </span>
    )
}
