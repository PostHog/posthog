import { useActions } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { attachedContextLogic } from '../logics/attachedContextLogic'
import type { AttachedContextItem } from '../types/contextTypes'

export interface UseAttachedContextOptions {
    /** When false, the provider is deregistered (nothing attached). Defaults to true. */
    active?: boolean
}

/**
 * Registers `items` into the global `attachedContextLogic` under a stable per-mount provider id, so
 * the PostHog AI surface picks them up as `<posthog_context>` at send time. Re-registers when the
 * items change (memoized on their JSON shape), and deregisters on unmount or when `active: false`.
 */
export function useAttachedContext(items: AttachedContextItem[] | null, options?: UseAttachedContextOptions): void {
    const active = options?.active ?? true
    const { registerContext, deregisterContext } = useActions(attachedContextLogic)
    const providerIdRef = useRef<string>(`ctx-${uuid()}`)
    // Memo key so re-renders that produce an equal array don't churn the registry.
    const itemsKey = useMemo(() => JSON.stringify(items ?? []), [items])

    useEffect(() => {
        const providerId = providerIdRef.current
        if (!active || !items || items.length === 0) {
            deregisterContext(providerId)
            return
        }
        registerContext(providerId, items)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, itemsKey, registerContext, deregisterContext])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterContext(providerId)
    }, [deregisterContext])
}
