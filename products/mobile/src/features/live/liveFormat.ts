import { plural } from '@/model/adapters/text'
import type { LiveProjectState, LiveWorld } from '@/model/live'

import type { LiveStatus } from './liveController'

/** "just now", "12 s ago", "3 min ago": live data is never older than a few minutes on screen. */
export function agoText(at: number, now: number): string {
    const seconds = Math.max(0, Math.floor((now - at) / 1000))
    if (seconds < 5) {
        return 'just now'
    }
    if (seconds < 60) {
        return `${seconds} s ago`
    }
    const minutes = Math.floor(seconds / 60)
    return minutes < 60 ? `${minutes} min ago` : `${Math.floor(minutes / 60)} h ago`
}

export function statusText(
    status: LiveStatus,
    updatedAt: number | null,
    now: number,
    state: LiveProjectState | null = null
): string {
    if (state === 'not_set_up') {
        return 'Not receiving events yet'
    }
    switch (status) {
        case 'paused':
            return 'Paused'
        case 'reconnecting':
            return 'Reconnecting…'
        case 'loading':
            return 'Loading…'
        case 'live':
            if (state === 'quiet') {
                return 'Live · waiting for activity'
            }
            return updatedAt === null ? 'Live' : `Live · updated ${agoText(updatedAt, now)}`
    }
}

/** A country as the map captions name it: "🇺🇸 United States", or the name alone when the code has no flag. */
export function countryText(country: { label: string; flag: string | null }): string {
    return country.flag ? `${country.flag} ${country.label}` : country.label
}

/** The countries screen's status line: "73 visitors in 18 countries · last 30 minutes", led by "Paused" when paused. */
export function countriesStatusText(status: LiveStatus, world: LiveWorld | null): string {
    if (!world || status === 'loading') {
        return 'Loading…'
    }
    if (status === 'reconnecting') {
        return 'Reconnecting…'
    }
    const summary = `${plural(world.total, 'visitor')} in ${plural(world.countries.length, 'country', 'countries')} · last 30 minutes`
    return status === 'paused' ? `Paused · ${summary}` : summary
}
