import { capabilitiesOf, tileShapeOf } from '@/model/adapters/insightSnapshot'
import type { InsightSnapshot, PinDisplay, PinView } from '@/model/views'

import { queryDisplay } from './snapshotChart'

export const AUTOMATIC_PIN_LIMIT = 3
export type PinDisplayPrefs = Readonly<Record<string, PinDisplay>>

export interface PinDisplayCandidate {
    display: Omit<PinDisplay, 'mode'>
    query: unknown
    snapshot?: InsightSnapshot
}

export function automaticPinCandidates(pins: readonly PinView[], prefs: PinDisplayPrefs): PinView[] {
    return pins
        .filter(
            (pin) =>
                pin.native &&
                (pin.kind === 'insight' || pin.kind === 'dashboard') &&
                prefs[pin.shortcutId] === undefined
        )
        .slice(0, AUTOMATIC_PIN_LIMIT)
}

export function automaticPinMode(query: unknown): 'number' | 'chart' | null {
    const shape = tileShapeOf(query)
    if (shape.hasBreakdown || shape.seriesCount > 1) {
        return null
    }
    const capabilities = capabilitiesOf(query)
    if (queryDisplay(query) === 'number' && capabilities.number) {
        return 'number'
    }
    return capabilities.chart && capabilities.number ? 'chart' : null
}

function ready(candidate: PinDisplayCandidate): boolean {
    const snapshot = candidate.snapshot
    return Boolean(
        snapshot?.lastRefreshAt &&
            !snapshot.refreshFailed &&
            (snapshot.value !== null || snapshot.series?.points.some((point) => Number.isFinite(point.value)))
    )
}

export function selectPinDisplay(candidates: readonly PinDisplayCandidate[]): PinDisplay | null {
    const ranked = candidates
        .map((candidate, index) => ({ candidate, index, mode: automaticPinMode(candidate.query) }))
        .filter((entry) => entry.mode !== null)
        .sort((a, b) => Number(ready(b.candidate)) - Number(ready(a.candidate)) || a.index - b.index)
    const first = ranked[0]
    return first?.mode ? { ...first.candidate.display, mode: first.mode } : null
}

export function resolvePinDisplays(
    pins: readonly PinView[],
    prefs: PinDisplayPrefs,
    automatic: PinDisplayPrefs
): PinView[] {
    return pins.map((pin) => {
        const display = prefs[pin.shortcutId] ?? automatic[pin.shortcutId]
        return display && pin.native ? { ...pin, display } : pin
    })
}
