import { useActions } from 'kea'
import { useEffect, useRef } from 'react'

import { uuid } from 'lib/utils/dom'

import { artifactActionsLogic } from '../logics/artifactActionsLogic'
import type { VisualizationArtifactAction } from '../types/artifactActionTypes'

export interface UseArtifactActionOptions {
    /** When false, the provider is deregistered (no button is offered). Defaults to true. */
    active?: boolean
}

/**
 * Registers `action` into the global `artifactActionsLogic` under a stable per-mount provider id, so
 * every visualization card in the thread offers it. Re-registers when the action's identity or label
 * changes, and deregisters on unmount or when `active: false`.
 *
 * `onSelect` is read at click time, so a host does not have to memoize it.
 */
export function useArtifactAction(
    action: VisualizationArtifactAction | null,
    options?: UseArtifactActionOptions
): void {
    const active = options?.active ?? true
    const { registerArtifactAction, deregisterArtifactAction } = useActions(artifactActionsLogic)
    const providerIdRef = useRef<string>(`artifact-action-${uuid()}`)
    const actionRef = useRef(action)
    actionRef.current = action
    // Keyed on id and label, the two values that change what the button shows. A fresh `onSelect`
    // closure on every render would otherwise churn the registry once per parent render, and an
    // element cannot go in the key, so a host that swaps only the icon re-renders without effect.
    const actionKey = action ? `${action.id}:${action.label}` : null

    useEffect(() => {
        const providerId = providerIdRef.current
        const current = actionRef.current
        if (!active || !current) {
            deregisterArtifactAction(providerId)
            return
        }
        registerArtifactAction(providerId, {
            ...current,
            onSelect: (payload) => actionRef.current?.onSelect(payload),
        })
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, actionKey, registerArtifactAction, deregisterArtifactAction])

    useEffect(() => {
        const providerId = providerIdRef.current
        return () => deregisterArtifactAction(providerId)
    }, [deregisterArtifactAction])
}
