import type { MCPIntentClusterJourneyApi } from '../generated/api.schemas'
import { JourneySankey } from '../JourneySankey'

interface Props {
    journey: MCPIntentClusterJourneyApi | null | undefined
}

export function ClusterJourneySankey({ journey }: Props): JSX.Element | null {
    if (!journey) {
        return (
            <div className="bg-surface-secondary rounded p-4 text-xs text-muted">
                Not enough session data yet to plot a journey. Recompute after more sessions are summarised.
            </div>
        )
    }

    return (
        <JourneySankey
            paths={journey.paths}
            totalSessions={journey.total_sessions}
            leak={journey.leak}
            emptyMessage="Not enough session data yet to plot a journey. Recompute after more sessions are summarised."
        />
    )
}
