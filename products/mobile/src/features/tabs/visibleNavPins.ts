import { MAX_NAV_PINS, type NavPin } from './navPinStore'
import type { TabKey } from './tabHeaderStore'

export function visibleNavPins(
    pins: readonly NavPin[],
    tab: TabKey,
    flags: Record<NavPin, boolean>
): readonly NavPin[] {
    const visible =
        (tab === 'errors' || tab === 'replay') && !pins.includes(tab) ? [...pins, tab].slice(-MAX_NAV_PINS) : pins
    return visible.filter((pin) => flags[pin])
}
