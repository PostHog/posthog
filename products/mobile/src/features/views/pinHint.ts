import { useCallback, useEffect, useMemo, useRef } from 'react'

import type { PinView } from '@/model/views'

import { type PinHintDismissReason, trackPinHintDismissed, trackPinHintShown } from './analytics'
import { usePinHintHydrated, usePinHintStore } from './pinHintStore'
import { pinModes } from './pinHooks'
import type { PinDisplayPrefs } from './smartPinDisplay'

/**
 * The pin the long-press hint points at: the first pin that offers Number and Chart and already shows an automatic
 * visual, so "Show as" has something real to change. Null once any pin has a display chosen on this phone, because
 * that person has found the menu.
 */
export function pinHintTarget(
    pins: readonly PinView[],
    automatic: PinDisplayPrefs,
    explicit: PinDisplayPrefs
): PinView | null {
    if (pins.some((pin) => explicit[pin.shortcutId] !== undefined)) {
        return null
    }
    return pins.find((pin) => pinModes(pin).length > 1 && automatic[pin.shortcutId] !== undefined) ?? null
}

export interface PinHintInput {
    pins: readonly PinView[] | undefined
    automatic: PinDisplayPrefs
    explicit: PinDisplayPrefs
    /** False in Edit pins and while searching. */
    enabled: boolean
}

export interface PinHint {
    /** The pin to show the hint under, or null when the hint is hidden. */
    target: PinView | null
    dismiss: (reason: PinHintDismissReason) => void
}

/** The one-time hint that a pin has a long-press menu. Dismissal lasts on this phone. */
export function usePinHint({ pins, automatic, explicit, enabled }: PinHintInput): PinHint {
    const hydrated = usePinHintHydrated()
    const dismissed = usePinHintStore((state) => state.dismissed)
    const candidate = useMemo(
        () => (pins ? pinHintTarget(pins, automatic, explicit) : null),
        [pins, automatic, explicit]
    )
    const target = hydrated && !dismissed && enabled ? candidate : null

    const shown = useRef<PinView | null>(null)
    shown.current = target
    const shownId = target?.shortcutId ?? null
    useEffect(() => {
        const pin = shown.current
        if (shownId && pin) {
            trackPinHintShown({ kind: pin.kind, mode: pin.display.mode })
        }
    }, [shownId])

    // A long press retires the hint even when it was not on screen, but only a visible hint sends the dismissed event.
    const dismiss = useCallback((reason: PinHintDismissReason) => {
        const store = usePinHintStore.getState()
        if (store.dismissed) {
            return
        }
        store.dismiss()
        if (shown.current) {
            trackPinHintDismissed({ reason })
        }
    }, [])

    return { target, dismiss }
}
