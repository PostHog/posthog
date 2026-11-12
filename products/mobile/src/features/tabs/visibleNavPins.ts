import { isNavPin, MAX_NAV_PINS, type NavPin } from './navPinStore'
import type { TabKey } from './tabHeaderStore'

/** Errors and Sessions follow their release flags. A pin without a flag here is always on. */
export type NavPinFlags = Partial<Record<NavPin, boolean>>

export function navPinEnabled(pin: NavPin, flags: NavPinFlags): boolean {
    return flags[pin] ?? true
}

export function visibleNavPins(pins: readonly NavPin[], tab: TabKey, flags: NavPinFlags): readonly NavPin[] {
    const visible = isNavPin(tab) && !pins.includes(tab) ? [...pins, tab].slice(-MAX_NAV_PINS) : pins
    return visible.filter((pin) => navPinEnabled(pin, flags))
}
