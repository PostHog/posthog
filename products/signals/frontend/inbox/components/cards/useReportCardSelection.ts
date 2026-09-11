import { useActions, useValues } from 'kea'
import { MouseEvent, PointerEvent, useCallback, useEffect, useRef, useState } from 'react'

import { captureInboxSelectionModeEntered, InboxSelectionEntryMethod } from '../../inboxAnalytics'
import { inboxBulkActionsLogic } from '../../logics/inboxBulkActionsLogic'
import {
    isNestedControlClick,
    resolveReportCardClickIntent,
    SELECTION_HOLD_MOVE_TOLERANCE_PX,
    SELECTION_HOLD_MS,
} from '../../utils/reportSelection'

export interface ReportCardSelection {
    isSelected: boolean
    /** True once anything is selected: every card then toggles on a plain click. */
    selectionMode: boolean
    /** Set while a hold is running, so the card suppresses text selection under the finger. */
    isHolding: boolean
    /** True while a bulk request owns the current selection. */
    selectionDisabled: boolean
    /** Select or deselect this report, naming the affordance the person used. */
    toggle: (method: InboxSelectionEntryMethod) => void
    /**
     * Handlers for the wrapper around the card body. The click is handled in the capture phase,
     * so selection can stop navigation before the body's `Link` handles the click.
     */
    cardHandlers: {
        onClickCapture: (event: MouseEvent) => void
        onPointerDown: (event: PointerEvent) => void
        onPointerMove: (event: PointerEvent) => void
        onPointerUp: () => void
        onPointerLeave: () => void
        onPointerCancel: () => void
    }
}

/**
 * Multi-select gestures for one report row: press and hold, shift-range, and the
 * gutter checkbox. The selection itself lives in `inboxBulkActionsLogic`; this hook only turns
 * pointer events into its actions, and it does nothing at all on a row the list marks unselectable.
 */
export function useReportCardSelection(reportId: string, enabled: boolean): ReportCardSelection {
    const { selectedReportIds, hasSelection, isDismissing, isResolving } = useValues(inboxBulkActionsLogic)
    const { toggleReportSelection, selectRange } = useActions(inboxBulkActionsLogic)
    const selectionDisabled = isDismissing || isResolving

    const holdTimerRef = useRef<number | null>(null)
    const holdOriginRef = useRef<{ x: number; y: number } | null>(null)
    // A hold selects on pointerup's own click too, so that click must not also open the report.
    const suppressClickRef = useRef(false)
    const [isHolding, setIsHolding] = useState(false)

    const cancelHold = useCallback((): void => {
        if (holdTimerRef.current !== null) {
            window.clearTimeout(holdTimerRef.current)
            holdTimerRef.current = null
        }
        holdOriginRef.current = null
        setIsHolding(false)
    }, [])
    useEffect(() => cancelHold, [cancelHold])

    const toggle = useCallback(
        (method: InboxSelectionEntryMethod): void => {
            if (selectionDisabled) {
                return
            }
            if (!hasSelection) {
                captureInboxSelectionModeEntered({ method })
            }
            toggleReportSelection(reportId)
        },
        [hasSelection, reportId, selectionDisabled, toggleReportSelection]
    )

    const onPointerDown = useCallback(
        (event: PointerEvent): void => {
            // A touch that never produces a click would otherwise leave the suppression armed for
            // the next press.
            suppressClickRef.current = false
            // Only the primary button holds; modified clicks have separate actions.
            if (
                !enabled ||
                selectionDisabled ||
                event.button !== 0 ||
                event.shiftKey ||
                event.metaKey ||
                event.ctrlKey
            ) {
                return
            }
            holdOriginRef.current = { x: event.clientX, y: event.clientY }
            setIsHolding(true)
            holdTimerRef.current = window.setTimeout(() => {
                holdTimerRef.current = null
                holdOriginRef.current = null
                setIsHolding(false)
                suppressClickRef.current = true
                toggle('long_press')
            }, SELECTION_HOLD_MS)
        },
        [enabled, selectionDisabled, toggle]
    )

    const onPointerMove = useCallback(
        (event: PointerEvent): void => {
            const origin = holdOriginRef.current
            if (!origin) {
                return
            }
            const travelled = Math.hypot(event.clientX - origin.x, event.clientY - origin.y)
            if (travelled > SELECTION_HOLD_MOVE_TOLERANCE_PX) {
                cancelHold()
            }
        },
        [cancelHold]
    )

    const onClick = useCallback(
        (event: MouseEvent): void => {
            if (!enabled || event.metaKey || event.ctrlKey || event.button !== 0) {
                return
            }
            if (suppressClickRef.current) {
                suppressClickRef.current = false
                event.preventDefault()
                event.stopPropagation()
                return
            }
            // Keep the current selection stable until its request finishes. A row click must not
            // open the report while the list still shows selection mode.
            if (selectionDisabled) {
                if (hasSelection) {
                    event.preventDefault()
                    event.stopPropagation()
                }
                return
            }
            // A shift-click on a nested link belongs to that link, not the row's selection.
            if (event.shiftKey && isNestedControlClick(event.target, event.currentTarget)) {
                return
            }
            const intent = resolveReportCardClickIntent(event, hasSelection)
            if (intent === 'open') {
                return
            }
            // The card body is a link, so every selecting click has to stop the navigation.
            event.preventDefault()
            event.stopPropagation()
            if (intent === 'range') {
                // A shift-click can open selection mode on its own, and it never goes through
                // `toggle`, so it records its own entry.
                if (!hasSelection) {
                    captureInboxSelectionModeEntered({ method: 'shift_click' })
                }
                selectRange(reportId)
                return
            }
            toggleReportSelection(reportId)
        },
        [enabled, hasSelection, reportId, selectRange, selectionDisabled, toggleReportSelection]
    )

    return {
        isSelected: enabled && selectedReportIds.includes(reportId),
        selectionMode: enabled && hasSelection,
        isHolding,
        selectionDisabled,
        toggle,
        cardHandlers: {
            onClickCapture: onClick,
            onPointerDown,
            onPointerMove,
            onPointerUp: cancelHold,
            onPointerLeave: cancelHold,
            onPointerCancel: cancelHold,
        },
    }
}
