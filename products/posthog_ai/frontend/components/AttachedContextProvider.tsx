import { useAttachedContext } from '../hooks/useAttachedContext'
import type { AttachedContextItem } from '../types/contextTypes'

export interface AttachedContextProviderProps {
    items: AttachedContextItem[] | null
    active?: boolean
}

/**
 * Render-null wrapper over `useAttachedContext` for JSX-only call sites that can't call the hook
 * directly. Attaches `items` to the PostHog AI surface for as long as it's mounted.
 */
export function AttachedContextProvider({ items, active }: AttachedContextProviderProps): null {
    useAttachedContext(items, { active })
    return null
}
