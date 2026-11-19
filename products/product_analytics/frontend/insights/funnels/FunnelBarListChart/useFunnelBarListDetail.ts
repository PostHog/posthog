import { type RefObject, useEffect, useLayoutEffect, useState } from 'react'
import { flushSync } from 'react-dom'

export type FunnelBarListDetail = 'full' | 'nouns' | 'counts' | 'compact' | 'percentages'

const DETAIL_LEVELS: FunnelBarListDetail[] = ['full', 'nouns', 'counts', 'compact', 'percentages']

// Dropping the counts costs more than a truncated name, so that last step waits until a name is nearly hidden.
const MIN_NAME_WIDTH = 32

function needsLessDetail(name: HTMLElement, nextDetail: FunnelBarListDetail): boolean {
    // Measures the laid-out text, because names can truncate inside a nested element that scrollWidth doesn't see.
    const range = document.createRange()
    range.selectNodeContents(name)
    const textWidth = range.getBoundingClientRect().width
    const style = getComputedStyle(name)
    const available = name.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    if (nextDetail === 'percentages') {
        return available < Math.min(textWidth, MIN_NAME_WIDTH)
    }
    return textWidth > available + 1
}

/** The most detailed text that leaves every step name untruncated, rechecked when the width or content changes. */
export function useFunnelBarListDetail(
    containerRef: RefObject<HTMLElement | null>,
    content: unknown
): FunnelBarListDetail {
    const [fit, setFit] = useState({ content, level: 0 })
    const level = fit.content === content ? fit.level : 0

    useEffect(() => {
        const container = containerRef.current
        if (!container) {
            return
        }
        let width = container.clientWidth
        const observer = new ResizeObserver(() => {
            if (container.clientWidth !== width) {
                width = container.clientWidth
                // Synchronous so the fuller text is measured and stepped down again before paint.
                flushSync(() => setFit((current) => ({ ...current, level: 0 })))
            }
        })
        observer.observe(container)
        return () => observer.disconnect()
    }, [containerRef, content])

    useLayoutEffect(() => {
        const container = containerRef.current
        if (!container?.clientWidth || level === DETAIL_LEVELS.length - 1) {
            return
        }
        const names = container.querySelectorAll<HTMLElement>('[data-funnel-bar-list-name]')
        if (Array.from(names).some((name) => needsLessDetail(name, DETAIL_LEVELS[level + 1]))) {
            setFit({ content, level: level + 1 })
        }
    }, [containerRef, content, fit, level])

    return DETAIL_LEVELS[level]
}
