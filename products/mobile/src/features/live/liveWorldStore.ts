import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import type { LiveWorld } from '@/model/live'

export interface LiveWorldShare {
    users?: boolean
    webOnly?: boolean
    mobileOnly?: boolean
    world: LiveWorld | null
    paused: boolean
}

const EMPTY: LiveWorldShare = { world: null, paused: false, users: false, mobileOnly: false, webOnly: false }

/**
 * Live's countries and Pause state when its map card opened Visitors by country. That screen paints them at once and
 * reads only while Live is not paused. Written at push time, because Pause cannot change while the screen covers Live.
 */
export const useLiveWorldShare = create<LiveWorldShare>()(() => EMPTY)

export function clearLiveWorldShare(): void {
    useLiveWorldShare.setState(EMPTY)
}

addSessionEndTask(clearLiveWorldShare)
