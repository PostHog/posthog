import { useActions } from 'kea'
import { useId, useLayoutEffect } from 'react'

import { foregroundStreamLogic } from '../logics/foregroundStreamLogic'

/**
 * Registers `streamKey` as a foreground stream — a run rendered in a surface the user is watching —
 * for the lifetime of the calling mount, updating it when the key changes and clearing it on
 * unmount. Pass `null` when there is no active foreground run (e.g. the panel is showing its
 * composer or history). Registrations are keyed by a per-mount provider id, so co-mounted surfaces
 * (side panel + full-page run view) hold independent entries instead of fighting over one slot.
 *
 * Registers in a layout effect: it flushes synchronously in the commit, before any network callback
 * can deliver a permission frame to an already-open stream and auto-approve past the gate.
 *
 * Mount-scoped registration wrapper over `foregroundStreamLogic`, mirroring `useAttachedContext`.
 */
export function useForegroundStream(streamKey: string | null): void {
    const { setForegroundStream, clearForegroundStream } = useActions(foregroundStreamLogic)
    const providerId = useId()

    useLayoutEffect(() => {
        if (!streamKey) {
            return
        }
        setForegroundStream(streamKey, providerId)
        return () => clearForegroundStream(providerId)
    }, [streamKey, providerId, setForegroundStream, clearForegroundStream])
}
