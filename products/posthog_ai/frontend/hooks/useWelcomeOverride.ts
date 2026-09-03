import { useActions } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { welcomeOverrideLogic } from '../logics/welcomeOverrideLogic'

export interface UseWelcomeOverrideOptions {
    /** When false, the provider is deregistered (defaults apply). Defaults to true. */
    active?: boolean
}

/**
 * Registers contextual welcome headlines into the global `welcomeOverrideLogic` under a stable
 * per-mount provider id, so the composer's empty state uses them instead of the generic defaults.
 * Deregisters on unmount or when `active: false`.
 */
export function useWelcomeOverride(headlines: string[] | null, options?: UseWelcomeOverrideOptions): void {
    const active = options?.active ?? true
    const { registerHeadlines, deregisterHeadlines } = useActions(welcomeOverrideLogic)
    const providerIdRef = useRef<string>(`welcome-${uuid()}`)
    // Memo key so re-renders that produce an equal array don't churn the registry.
    const headlinesKey = useMemo(() => JSON.stringify(headlines ?? []), [headlines])

    useEffect(() => {
        const providerId = providerIdRef.current
        if (!active || !headlines || headlines.length === 0) {
            deregisterHeadlines(providerId)
            return
        }
        registerHeadlines(providerId, headlines)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, headlinesKey, registerHeadlines, deregisterHeadlines])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterHeadlines(providerId)
    }, [deregisterHeadlines])
}
