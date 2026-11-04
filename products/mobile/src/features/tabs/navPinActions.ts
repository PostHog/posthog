import { track } from '@/lib/analytics'

import { type NavPin, replacedNavPin, restoreNavPins, setNavPinned, useNavPinStore } from './navPinStore'

const LABELS: Record<NavPin, string> = { errors: 'Errors', replay: 'Sessions' }

/** Where a pin change started. `undo` is the toast's Undo, which reverses the change just before it. */
export type NavPinSource = 'views_row' | 'list_menu' | 'undo'

function trackNavPinChanged(pin: NavPin, pinned: boolean, source: NavPinSource, replaced: boolean): void {
    track('mobile_nav_pin_changed', { pin, pinned, source, replaced })
}

/**
 * Pins or unpins a list in the navigation and confirms it with a toast that can undo it. A pin at the cap replaces the
 * other list, and Undo puts that one back. `show` is the screen's `useToasts().show`, so the toast draws where that
 * screen draws its others.
 */
export function changeNavPin(
    pin: NavPin,
    pinned: boolean,
    source: Exclude<NavPinSource, 'undo'>,
    show: (text: string, undo?: () => void) => void
): void {
    const before = useNavPinStore.getState().pins
    const replaced = pinned ? replacedNavPin(before, pin) : null
    setNavPinned(pin, pinned)
    trackNavPinChanged(pin, pinned, source, replaced !== null)
    const text = replaced
        ? `Pinned, replacing ${LABELS[replaced]}`
        : pinned
          ? 'Pinned to navigation'
          : 'Unpinned from navigation'
    show(text, () => {
        restoreNavPins(before)
        trackNavPinChanged(pin, !pinned, 'undo', replaced !== null)
    })
}
