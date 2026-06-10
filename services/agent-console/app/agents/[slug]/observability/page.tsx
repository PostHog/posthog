/**
 * `/agents/[slug]/observability` — per-agent AI observability tab.
 *
 * The same rollups as the fleet `/analytics` board, scoped to this one agent
 * (its `$ai_*` events in the team's own project), with a kick-out to the full
 * AI observability product for trace-level depth.
 */

import { ObservabilitySegment } from './observability-client'

export default function AgentObservabilityPage(): React.ReactElement {
    return <ObservabilitySegment />
}
