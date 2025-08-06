import { useCallback, useRef } from 'react'

export type ScrollObserverOptions = {
    onScrollTop?: () => void
    onScrollBottom?: () => void
}

export function useScrollObserver({ onScrollTop, onScrollBottom }: ScrollObserverOptions = {}): (
    el: HTMLDivElement | null
) => void {
    const containerRef = useRef<HTMLDivElement | null>(null)
    const scrollHandlerRef = useRef<() => void>()

    const handleScroll = useCallback(
        (el: HTMLDivElement) => {
            return async () => {
                const scrollTop = el.scrollTop
                const scrollHeight = el.scrollHeight
                const clientHeight = el.clientHeight
                const scrollRatio = scrollTop / (scrollHeight - clientHeight)

                if (scrollRatio <= 0) {
                    onScrollTop?.()
                }

                if (scrollRatio >= 1) {
                    onScrollBottom?.()
                }
            }
        },
        [onScrollTop, onScrollBottom]
    )

    return useCallback(
        (el: HTMLDivElement | null) => {
            if (!el) {
                // Component is unmounted
                if (scrollHandlerRef.current && !!containerRef.current) {
                    containerRef.current.removeEventListener('scroll', scrollHandlerRef.current)
                }
            } else {
                // Component is mounted
                containerRef.current = el
                scrollHandlerRef.current = handleScroll(el)
                el.addEventListener('scroll', scrollHandlerRef.current)
            }
        },
        [handleScroll]
    )
}
