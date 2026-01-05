import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useRef } from 'react'

import { virtualizedLogsListLogic } from './virtualizedLogsListLogic'

const SCROLL_INTERVAL_MS = 16
const SCROLL_AMOUNT_PX = 8

// Hook for the component that owns the scrollable element (e.g., MessageCell)
export interface UseCellScrollRefOptions {
    tabId: string
    cellKey: string
    enabled?: boolean
}

export interface UseCellScrollRefResult {
    scrollRef: React.RefObject<HTMLDivElement>
    handleScroll: (e: React.UIEvent<HTMLDivElement>) => void
}

export function useCellScrollRef({ tabId, cellKey, enabled = true }: UseCellScrollRefOptions): UseCellScrollRefResult {
    const { cellScrollLefts } = useValues(virtualizedLogsListLogic({ tabId }))
    const { setCellScrollLeft } = useActions(virtualizedLogsListLogic({ tabId }))

    const scrollRef = useRef<HTMLDivElement>(null)
    const isProgrammaticScrollRef = useRef(false)

    const scrollLeft = cellScrollLefts[cellKey] ?? 0

    // Sync scroll position from shared state to DOM
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

    return {
        scrollRef,
        handleScroll,
    }
}

// Hook for the component that controls scrolling (e.g., LogRowFAB)
export interface UseCellScrollControlsOptions {
    tabId: string
    cellKey: string
}

export interface UseCellScrollControlsResult {
    startScrolling: (direction: 'left' | 'right') => void
    stopScrolling: () => void
}

export function useCellScrollControls({ tabId, cellKey }: UseCellScrollControlsOptions): UseCellScrollControlsResult {
    const { cellScrollLefts } = useValues(virtualizedLogsListLogic({ tabId }))
    const { setCellScrollLeft } = useActions(virtualizedLogsListLogic({ tabId }))

    const scrollIntervalRef = useRef<number | null>(null)
    const scrollRef = useRef<((direction: 'left' | 'right') => void) | null>(null)

    // Keep scroll function fresh (pattern from useInterval)
    useEffect(() => {
        scrollRef.current = (direction: 'left' | 'right'): void => {
            const currentScrollLeft = cellScrollLefts[cellKey] ?? 0
            const newScrollLeft =
                direction === 'left'
                    ? Math.max(0, currentScrollLeft - SCROLL_AMOUNT_PX)
                    : currentScrollLeft + SCROLL_AMOUNT_PX
            setCellScrollLeft(cellKey, newScrollLeft)
        }
    }, [cellScrollLefts, cellKey, setCellScrollLeft])

    const startScrolling = (direction: 'left' | 'right'): void => {
        if (scrollIntervalRef.current !== null) {
            return
        }
        scrollRef.current?.(direction)
        scrollIntervalRef.current = window.setInterval(() => {
            scrollRef.current?.(direction)
        }, SCROLL_INTERVAL_MS)
    }

    const stopScrolling = (): void => {
        if (scrollIntervalRef.current) {
            clearInterval(scrollIntervalRef.current)
            scrollIntervalRef.current = null
        }
    }

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
        startScrolling,
        stopScrolling,
    }
}

// Combined hook for backward compatibility (used when one component needs both)
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

/** @deprecated Use useCellScrollRef and useCellScrollControls instead */
export function useCellScroll({ tabId, cellKey, enabled = true }: UseCellScrollOptions): UseCellScrollResult {
    const { scrollRef, handleScroll } = useCellScrollRef({ tabId, cellKey, enabled })
    const { startScrolling, stopScrolling } = useCellScrollControls({ tabId, cellKey })

    return {
        scrollRef,
        handleScroll,
        startScrolling,
        stopScrolling,
    }
}
