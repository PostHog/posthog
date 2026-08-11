import type React from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { useSelfDrivingRunInFlight } from 'scenes/onboarding/shared/wizard-sync/hooks'

/**
 * A quiet one-liner for empty states while the self-driving wizard is mid-run: the surface is empty
 * because setup hasn't finished, not because nothing works. The caller words what this surface is
 * waiting on; renders nothing when no run is going.
 */
export function SelfDrivingInstallingHint({ children }: { children: React.ReactNode }): JSX.Element | null {
    const runInFlight = useSelfDrivingRunInFlight()
    if (!runInFlight) {
        return null
    }
    return (
        <span className="inline-flex items-center gap-1.5 text-xs text-tertiary mt-1">
            <Spinner className="text-sm" />
            {children}
        </span>
    )
}
