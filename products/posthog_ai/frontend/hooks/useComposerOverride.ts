import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { ComposerOverride, composerOverrideLogic } from '../logics/composerOverrideLogic'

export interface UseComposerOverrideOptions {
    /** When false, the provider is deregistered (defaults apply). Defaults to true. */
    active?: boolean
}

/** Registers a composer override for this mount. Pass a module-level constant: registration is keyed on object identity. */
export function useComposerOverride(override: ComposerOverride | null, options?: UseComposerOverrideOptions): void {
    const active = options?.active ?? true
    const { registerComposerOverride, deregisterComposerOverride } = useActions(composerOverrideLogic)
    const providerIdRef = useRef<string>(`composer-${uuid()}`)

    useEffect(() => {
        const providerId = providerIdRef.current
        if (!active || !override) {
            deregisterComposerOverride(providerId)
            return
        }
        registerComposerOverride(providerId, override)
    }, [active, override, registerComposerOverride, deregisterComposerOverride])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterComposerOverride(providerId)
    }, [deregisterComposerOverride])
}
