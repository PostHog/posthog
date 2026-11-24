import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import type { LiveWorld } from '@/model/live'
import { DEFAULT_LIVE_TRAFFIC_FILTERS, type LiveTrafficFilters } from '@/model/liveTrafficFilters'

export interface LiveWorldShare {
    users?: boolean
    webOnly?: boolean
    mobileOnly?: boolean
    filterTestAccounts?: boolean
    trafficFilters?: LiveTrafficFilters
    world: LiveWorld | null
    paused: boolean
}

const EMPTY: LiveWorldShare = {
    world: null,
    paused: false,
    users: false,
    mobileOnly: false,
    webOnly: false,
    filterTestAccounts: false,
    trafficFilters: DEFAULT_LIVE_TRAFFIC_FILTERS,
}

/**
 * Live's countries and Pause state when its map card opened Visitors by country. That screen paints them at once and
 * reads only while Live is not paused. Written at push time, because Pause cannot change while the screen covers Live.
 */
export const useLiveWorldShare = create<LiveWorldShare>()(() => EMPTY)

export function clearLiveWorldShare(): void {
    useLiveWorldShare.setState(EMPTY)
}

addSessionEndTask(clearLiveWorldShare)
