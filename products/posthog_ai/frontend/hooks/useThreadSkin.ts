import { createContext, useContext } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ThreadSkin } from '../components/quill/quillThreadContext'

/**
 * Pins the skin for a subtree, whatever the flags say. A story or a test renders the lemon and the quill
 * chat side by side with it; product code leaves it unset and lets the flags decide.
 */
export const ThreadSkinOverrideContext = createContext<ThreadSkin | null>(null)

/**
 * The skin for every PostHog AI chat surface: the thread, the run composer and its pickers. The quill chat
 * is part of the quill web redesign, so `today-rail-nav` turns it on as well.
 */
export function useThreadSkin(): ThreadSkin {
    const override = useContext(ThreadSkinOverrideContext)
    const phaiQuill = useFeatureFlag('PHAI_QUILL')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (override) {
        return override
    }
    return phaiQuill || todayRailNav ? 'quill' : 'lemon'
}
