import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { virtualizedLogsListLogic } from './virtualizedLogsListLogic'

const SCROLL_INTERVAL_MS = 16
const SCROLL_AMOUNT_PX = 8

export interface UseCellScrollOptions {
    tabId: string
    cellKey: string
    enabled?: boolean
}

export interface UseCellScrollResult {
    scrollRef: React.RefObject<HTMLDivElement>
    handleScroll: (e: React.UIEvent<HTMLDivElement>) => void
    startScrolling: (direction: 'left' | 'right') => void
    stopScrolling: () => void
}

export function useCellScroll({ tabId, cellKey, enabled = true }: UseCellScrollOptions): UseCellScrollResult {
    const { cellScrollLefts } = useValues(virtualizedLogsListLogic({ tabId }))
    const { setCellScrollLeft } = useActions(virtualizedLogsListLogic({ tabId }))

    const scrollRef = useRef<HTMLDivElement>(null)
    const isProgrammaticScrollRef = useRef(false)
    const scrollIntervalRef = useRef<number | null>(null)

    const scrollLeft = cellScrollLefts[cellKey] ?? 0

    // Sync scroll position from shared state
    useEffect(() => {
        if (!enabled) {
            return
        }
        const el = scrollRef.current
        if (el && Math.abs(el.scrollLeft - scrollLeft) > 1) {
            isProgrammaticScrollRef.current = true
            el.scrollLeft = scrollLeft
            requestAnimationFrame(() => {
                isProgrammaticScrollRef.current = false
            })
        }
    }, [scrollLeft, enabled])

    const handleScroll = useCallback(
        (e: React.UIEvent<HTMLDivElement>): void => {
            if (isProgrammaticScrollRef.current) {
                return
            }
            setCellScrollLeft(cellKey, e.currentTarget.scrollLeft)
        },
        [cellKey, setCellScrollLeft]
    )

    const scroll = useCallback(
        (direction: 'left' | 'right'): void => {
            const el = scrollRef.current
            if (el) {
                const newScrollLeft =
                    direction === 'left'
                        ? Math.max(0, el.scrollLeft - SCROLL_AMOUNT_PX)
                        : el.scrollLeft + SCROLL_AMOUNT_PX
                el.scrollLeft = newScrollLeft
                setCellScrollLeft(cellKey, newScrollLeft)
            }
        },
        [cellKey, setCellScrollLeft]
    )

    const startScrolling = useCallback(
        (direction: 'left' | 'right'): void => {
            if (scrollIntervalRef.current !== null) {
                return
            }
            scroll(direction)
            scrollIntervalRef.current = window.setInterval(() => {
                scroll(direction)
            }, SCROLL_INTERVAL_MS)
        },
        [scroll]
    )

    const stopScrolling = useCallback((): void => {
        if (scrollIntervalRef.current) {
            clearInterval(scrollIntervalRef.current)
            scrollIntervalRef.current = null
        }
    }, [])

    // Cleanup interval on unmount
    useEffect(() => {
        return () => {
            if (scrollIntervalRef.current) {
                clearInterval(scrollIntervalRef.current)
                scrollIntervalRef.current = null
            }
        }
    }, [])

    return {
        scrollRef,
        handleScroll,
        startScrolling,
        stopScrolling,
    }
}
