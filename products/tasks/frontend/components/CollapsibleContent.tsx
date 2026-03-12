import { useEffect, useRef, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'

const DEFAULT_MAX_HEIGHT = 120

interface CollapsibleContentProps {
    maxHeight?: number
    gradientColor?: string
    children: React.ReactNode
}

export function CollapsibleContent({
    maxHeight = DEFAULT_MAX_HEIGHT,
    gradientColor = '--bg-light',
    children,
}: CollapsibleContentProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const [isOverflowing, setIsOverflowing] = useState(false)
    const contentRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        const el = contentRef.current
        if (el) {
            setIsOverflowing(el.scrollHeight > maxHeight)
        }
    }, [children, maxHeight])

    return (
        <>
            <div
                ref={contentRef}
                className="relative overflow-hidden transition-all"
                style={!isExpanded && isOverflowing ? { maxHeight } : undefined}
            >
                {children}
                {!isExpanded && isOverflowing && (
                    <div
                        className="pointer-events-none absolute inset-x-0 bottom-0 h-16"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ background: `linear-gradient(transparent, var(${gradientColor}))` }}
                    />
                )}
            </div>
            {isOverflowing && (
                <button
                    type="button"
                    onClick={() => setIsExpanded((prev) => !prev)}
                    className="mt-1 flex items-center gap-1 text-xs text-muted hover:text-default cursor-pointer"
                >
                    <IconChevronDown
                        className="transition-transform"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={isExpanded ? { transform: 'rotate(180deg)' } : undefined}
                    />
                    {isExpanded ? 'Show less' : 'Show more'}
                </button>
            )}
        </>
    )
}
