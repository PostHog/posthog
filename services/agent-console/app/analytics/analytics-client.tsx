'use client'

import { useSetDockPage } from '@/components/dock-context'
import { FleetAnalytics } from '@/components/FleetAnalytics'
import { usePosthogBaseUrl, useSessionTeamId } from '@/components/session-context'
import { EMPTY_ANALYTICS, loadFleetAnalytics } from '@/lib/fleetAnalytics'
import { aiObservabilityTracesUrl } from '@/lib/posthogLinks'
import { useResource } from '@/lib/useResource'

export function AnalyticsClient(): React.ReactElement {
    // SessionGate (in AppShell) blocks rendering until teamId resolves.
    const teamId = useSessionTeamId()!
    const posthogBaseUrl = usePosthogBaseUrl()

    // Fleet-wide concierge surface — same context kind as the agents list.
    useSetDockPage({ kind: 'agent-list' })

    // Polls so the board stays live. A hard failure (the KPI gate query throws)
    // surfaces as an error state; "no events yet" lands in the empty state.
    const analytics = useResource(() => loadFleetAnalytics(teamId), [teamId], { pollMs: 30_000 })

    return (
        <FleetAnalytics
            data={analytics.data ?? EMPTY_ANALYTICS}
            aiObservabilityUrl={posthogBaseUrl ? aiObservabilityTracesUrl(posthogBaseUrl, teamId) : undefined}
            loading={analytics.loading && !analytics.data}
            error={!analytics.loading && !analytics.data ? (analytics.error?.message ?? 'Failed to load') : null}
        />
    )
}
