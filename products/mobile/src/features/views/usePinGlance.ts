import type { Href } from 'expo-router'

import type { NumberDelta, PinView, ViewEntry } from '@/model/views'

import { deltaSpoken } from './DeltaPill'
import { viewTypeLabel } from './list/viewMeta'
import { type PinData, usePinData } from './pinHooks'
import { deltaBasisText, snapshotFormatter, valueAtText } from './snapshotChart'
import { viewHref } from './viewRoutes'

/** The sparkline shows the last 14 buckets, and the last 7 of them in blue. */
const SPARKLINE_BUCKETS = 14
const SPARKLINE_CURRENT = 7

export interface PinDelta {
    /** The props of `DeltaPill`. */
    props: { delta: NumberDelta; formatValue: (value: number) => string; basis: string }
    spoken: string
}

/** What a pin shows at a glance, from the data the Views list last read for it. */
export interface PinGlance {
    /** The second line: the tile name of a dashboard pin, else the view type. */
    subtitle: string
    format: ((value: number) => string) | null
    /** The formatted value. Null without a snapshot or a value. */
    value: string | null
    /** False when the view has no single number, so a glance shows no value. */
    hasNumber: boolean
    delta: PinDelta | null
    /** When the value was measured. */
    at: string | null
    sparkline: { values: number[]; highlightFrom: number }
}

export function pinGlance(pin: PinView, data: PinData): PinGlance {
    const { snapshot } = data
    const format = snapshot ? snapshotFormatter(snapshot) : null
    let delta: PinDelta | null = null
    if (snapshot?.delta && format) {
        const basis = deltaBasisText(snapshot.delta, snapshot.interval)
        delta = {
            props: { delta: snapshot.delta, formatValue: format, basis },
            spoken: deltaSpoken(snapshot.delta, format, basis),
        }
    }
    const values = (snapshot?.series?.points ?? []).slice(-SPARKLINE_BUCKETS).map((point) => point.value)
    return {
        subtitle: pin.kind === 'dashboard' ? (snapshot?.name ?? 'Dashboard') : viewTypeLabel(pin.kind),
        format,
        value: snapshot && format && snapshot.value !== null ? format(snapshot.value) : null,
        hasNumber: snapshot?.capabilities.number ?? false,
        delta,
        at: snapshot ? valueAtText(snapshot) : null,
        sparkline: { values, highlightFrom: values.length - SPARKLINE_CURRENT },
    }
}

/**
 * A pin at a glance outside the Views list, such as in Live's Meanwhile, with the route that opens it as `from`.
 * Mounting it sends nothing.
 */
export function usePinGlance(pin: PinView, from: ViewEntry): PinGlance & { href: Href | null } {
    const glance = pinGlance(pin, usePinData(pin))
    return { ...glance, href: viewHref(pin, { from, mode: pin.display.mode }) }
}
