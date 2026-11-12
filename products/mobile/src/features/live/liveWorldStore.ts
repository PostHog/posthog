import { create } from 'zustand'

import { addSessionEndTask } from '@/auth/authStore'
import type { LiveWorld } from '@/model/live'

export interface LiveWorldShare {
    world: LiveWorld | null
    paused: boolean
}

const EMPTY: LiveWorldShare = { world: null, paused: false }

/**
 * Live's last countries and its Pause state, for the countries screen that Live pushes. That screen paints them at
 * once, and reads only while Live is not paused.
 */
export const useLiveWorldShare = create<LiveWorldShare>()(() => EMPTY)

export function clearLiveWorldShare(): void {
    useLiveWorldShare.setState(EMPTY)
}

addSessionEndTask(clearLiveWorldShare)
