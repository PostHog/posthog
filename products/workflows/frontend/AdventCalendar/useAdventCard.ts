import { useCallback, useEffect, useRef, useState } from 'react'

export const ADVENT_CARD_CLOSE_MS = 220

export interface AdventCardState {
    doorId: string | null
    isOpen: boolean
    isPinned: boolean
    onEnterDoor: (doorId: string) => void
    onLeaveDoor: () => void
    onEnterCard: () => void
    clearHover: () => void
}

export function useAdventCard(pinnedDoorId: string | null, isEnabled: boolean): AdventCardState {
    const [hoveredId, setHoveredId] = useState<string | null>(null)
    const [shown, setShown] = useState<{ doorId: string | null; isOpen: boolean }>({ doorId: null, isOpen: false })
    const hoverTimer = useRef<number>()
    const targetId = isEnabled ? (pinnedDoorId ?? hoveredId) : null
    const quiet = useRef<{ doorId: string | null } | null>(null)
    const hover = useCallback((doorId: string): void => {
        window.clearTimeout(hoverTimer.current)
        setHoveredId(doorId)
    }, [])

    useEffect(() => {
        const wake = (): void => {
            const waiting = quiet.current?.doorId
            quiet.current = null
            if (waiting) {
                hover(waiting)
            }
        }
        window.addEventListener('pointermove', wake)
        return () => {
            window.removeEventListener('pointermove', wake)
            window.clearTimeout(hoverTimer.current)
        }
    }, [hover])

    useEffect(() => {
        if (targetId) {
            setShown({ doorId: targetId, isOpen: false })
            let second = 0
            const first = requestAnimationFrame(() => {
                second = requestAnimationFrame(() => setShown({ doorId: targetId, isOpen: true }))
            })
            return () => {
                cancelAnimationFrame(first)
                cancelAnimationFrame(second)
            }
        }
        setShown((current) => ({ ...current, isOpen: false }))
        const timer = window.setTimeout(() => setShown({ doorId: null, isOpen: false }), ADVENT_CARD_CLOSE_MS)
        return () => window.clearTimeout(timer)
    }, [targetId])

    return {
        doorId: shown.doorId,
        isOpen: shown.isOpen && shown.doorId === targetId,
        isPinned: !!pinnedDoorId && shown.doorId === pinnedDoorId,
        onEnterDoor: (doorId) => {
            if (quiet.current) {
                quiet.current.doorId = doorId
            } else {
                hover(doorId)
            }
        },
        onLeaveDoor: () => {
            if (quiet.current) {
                quiet.current.doorId = null
            }
            window.clearTimeout(hoverTimer.current)
            hoverTimer.current = window.setTimeout(() => setHoveredId(null), ADVENT_CARD_CLOSE_MS)
        },
        onEnterCard: () => window.clearTimeout(hoverTimer.current),
        clearHover: () => {
            window.clearTimeout(hoverTimer.current)
            quiet.current = { doorId: null }
            setHoveredId(null)
        },
    }
}
