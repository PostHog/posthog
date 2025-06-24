import React, { CSSProperties, MouseEvent } from 'react'
import { Transition } from 'react-transition-group'
import { ENTERED, ENTERING, EXITED, EXITING, UNMOUNTED } from 'react-transition-group/Transition'
import useResizeObserver from 'use-resize-observer'

export function Collapsible({
    children,
    isExpanded,
    className,
    minHeight = 0,
    onClick,
}: {
    children: React.ReactNode
    isExpanded: boolean
    className?: string
    minHeight?: string | number
    onClick?: (e: MouseEvent) => void
}): JSX.Element {
    const { height: contentHeight, ref: contentRef } = useResizeObserver({ box: 'border-box' })
    return (
        <div aria-expanded={isExpanded} onClick={onClick}>
            <Transition in={isExpanded} timeout={200}>
                {(status) => (
                    <div
                        // eslint-disable-next-line react/forbid-dom-props
                        style={getStyle(status, contentHeight, minHeight)}
                        className="overflow-hidden"
                        aria-busy={status.endsWith('ing')}
                    >
                        <div className={className} ref={contentRef}>
                            {children}
                        </div>
                    </div>
                )}
            </Transition>
        </div>
    )
}

type TransitionStatus = typeof ENTERED | typeof ENTERING | typeof EXITED | typeof EXITING | typeof UNMOUNTED

function getStyle(
    state: TransitionStatus,
    contentHeight: number | undefined,
    minHeight: string | number
): CSSProperties {
    switch (state) {
        case ENTERING:
            return { height: contentHeight, minHeight, transition: 'height 200ms ease-in-out' }
        case ENTERED:
            return { height: contentHeight, minHeight }
        case EXITING:
            return { height: minHeight, minHeight, transition: 'height 200ms ease-in-out' }
        case EXITED:
            return { height: minHeight, minHeight }
        default:
            return { height: minHeight, minHeight }
    }
}
