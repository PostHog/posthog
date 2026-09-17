import { LemonTag } from '@posthog/lemon-ui'

import { MCPDiscoverCandidateApi } from './generated/api.schemas'
import { MeasuredTag } from './MeasuredTag'

type LivenessLabel = { label: string; type: 'success' | 'warning' | 'danger' | 'muted' | 'default' }

/** Probe states are internal keys. People need to know whether the server answers. */
const LIVENESS: Record<string, LivenessLabel> = {
    alive_open: { label: 'Live, no sign-in', type: 'success' },
    alive_auth: { label: 'Live, needs sign-in', type: 'success' },
    alive_protocol: { label: 'Responds', type: 'default' },
    package_only: { label: 'Runs locally', type: 'muted' },
    unprobed: { label: 'Not checked yet', type: 'muted' },
    not_mcp: { label: 'Not an MCP server', type: 'warning' },
    dead: { label: 'Not responding', type: 'danger' },
}

export function Candidate({ candidate }: { candidate: MCPDiscoverCandidateApi }): JSX.Element {
    const liveness = LIVENESS[candidate.liveness] ?? { label: candidate.liveness, type: 'muted' as const }
    return (
        <li className="border rounded p-3 flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-muted tabular-nums">{candidate.rank}</span>
                <span className="font-semibold">{candidate.title}</span>
                <LemonTag type={liveness.type}>{liveness.label}</LemonTag>
                <MeasuredTag measured={candidate.measured} />
            </div>
            {candidate.registry_name ? (
                <code className="text-xs text-muted break-all">{candidate.registry_name}</code>
            ) : null}
            {candidate.description ? <p className="m-0 text-sm">{candidate.description}</p> : null}
            {candidate.matched_tools.length > 0 ? (
                <div className="flex gap-1 flex-wrap">
                    {candidate.matched_tools.map((tool) => (
                        <LemonTag key={tool.name} type="option">
                            {tool.name}
                        </LemonTag>
                    ))}
                </div>
            ) : null}
        </li>
    )
}
