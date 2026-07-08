import { useActions } from 'kea'
import { useEffect } from 'react'

import { foregroundStreamLogic } from '../logics/foregroundStreamLogic'

/**
 * Registers `streamKey` as the foreground stream — the run rendered in the side panel the user is
 * watching — for the lifetime of the calling mount, updating it when the key changes and clearing it
 * on unmount. Pass `null` when there is no active foreground run (e.g. the panel is showing its
 * composer or history). Clearing is key-checked in the logic, so an overlapping mount/unmount race
 * between two surfaces can't clobber the newer registration.
 *
 * Mount-scoped registration wrapper over `foregroundStreamLogic`, mirroring `useAttachedContext`.
 */
export function useForegroundStream(streamKey: string | null): void {
    const { setForegroundStream, clearForegroundStream } = useActions(foregroundStreamLogic)

    useEffect(() => {
        if (!streamKey) {
            return
        }
        setForegroundStream(streamKey)
        return () => clearForegroundStream(streamKey)
    }, [streamKey, setForegroundStream, clearForegroundStream])
}
