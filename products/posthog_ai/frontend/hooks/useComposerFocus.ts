import { useActions } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { composerFocusLogic } from '../logics/composerFocusLogic'
import type { ComposerFocus } from '../types/composerFocusTypes'

export interface UseComposerFocusOptions {
    /** When false, the provider is deregistered and the composer shows its welcome state. Defaults to true. */
    active?: boolean
}

/**
 * Registers `focus` into the global `composerFocusLogic` under a stable per-mount provider id, so the
 * composer pins it above the textbox. Deregisters on unmount or when `active: false`.
 */
export function useComposerFocus(focus: ComposerFocus | null, options?: UseComposerFocusOptions): void {
    const active = options?.active ?? true
    const { registerFocus, deregisterFocus } = useActions(composerFocusLogic)
    const providerIdRef = useRef<string>(`composer-focus-${uuid()}`)
    // A JSON key, so a re-render that builds an equal focus object does not churn the registry.
    const focusKey = useMemo(() => JSON.stringify(focus), [focus])

    useEffect(() => {
        const providerId = providerIdRef.current
        if (!active || !focus) {
            deregisterFocus(providerId)
            return
        }
        registerFocus(providerId, focus)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, focusKey, registerFocus, deregisterFocus])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterFocus(providerId)
    }, [deregisterFocus])
}
