import { MouseEvent, RefObject, useEffect, useRef, useState } from 'react'

import { isHeadingToRect, Point } from './tileCanvasModel'

const PREVIEW_DWELL_MS = 650
const SAFE_TRIANGLE_SLACK = 12
const SWITCH_AFTER_MS = 140

export interface MiniFlowSpotlight {
    spotlightId: string | null
    showPreview: boolean
    previewRef: RefObject<HTMLDivElement>
    enterStep: (actionId: string) => void
    leaveStep: (actionId: string) => void
    enterPreview: () => void
    trackPointer: (event: MouseEvent) => void
    leaveFlow: () => void
}

/**
 * Which step of a peek shows its card. A step the pointer crosses on its way down to the open card must not
 * take the card away, so a new step wins only once the pointer leaves the path toward the card.
 */
export function useMiniFlowSpotlight(open: boolean): MiniFlowSpotlight {
    const [spotlightId, setSpotlightId] = useState<string | null>(null)
    const [showPreview, setShowPreview] = useState(false)
    const pointer = useRef<Point>({ x: 0, y: 0 })
    const apex = useRef<Point | null>(null)
    const overId = useRef<string | null>(null)
    const switchTimer = useRef<number>()
    const previewRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        setShowPreview(false)
        if (!spotlightId) {
            return
        }
        const timer = window.setTimeout(() => setShowPreview(true), PREVIEW_DWELL_MS)
        return () => window.clearTimeout(timer)
    }, [spotlightId])

    useEffect(() => {
        if (!open) {
            setSpotlightId(null)
        }
    }, [open])

    useEffect(() => () => window.clearTimeout(switchTimer.current), [])

    const isHeadingToPreview = (): boolean => {
        const preview = previewRef.current?.getBoundingClientRect()
        return (
            !!preview && !!apex.current && isHeadingToRect(pointer.current, apex.current, preview, SAFE_TRIANGLE_SLACK)
        )
    }

    return {
        spotlightId,
        showPreview,
        previewRef,
        enterStep: (actionId) => {
            overId.current = actionId
            window.clearTimeout(switchTimer.current)
            if (spotlightId && spotlightId !== actionId && isHeadingToPreview()) {
                switchTimer.current = window.setTimeout(() => {
                    if (overId.current === actionId) {
                        setSpotlightId(actionId)
                    }
                }, SWITCH_AFTER_MS)
                return
            }
            setSpotlightId(actionId)
        },
        leaveStep: (actionId) => {
            if (overId.current === actionId) {
                overId.current = null
            }
        },
        enterPreview: () => {
            overId.current = spotlightId
            window.clearTimeout(switchTimer.current)
        },
        trackPointer: (event) => {
            pointer.current = { x: event.clientX, y: event.clientY }
            if (overId.current && overId.current === spotlightId) {
                apex.current = pointer.current
            }
        },
        leaveFlow: () => {
            window.clearTimeout(switchTimer.current)
            overId.current = null
            setSpotlightId(null)
        },
    }
}
