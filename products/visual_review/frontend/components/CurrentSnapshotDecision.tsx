import { TZLabel } from 'lib/components/TZLabel'

import type { SnapshotDecisionApi } from '../generated/api.schemas'
import { personName, shortSha } from '../lib/reviewDecisions'

// Each text is the only child of its element. A page translator replaces text nodes, and React cannot update or
// remove a text node it no longer finds next to its siblings.
export function CurrentSnapshotDecision({ decision }: { decision: SnapshotDecisionApi }): JSX.Element {
    const name = personName(decision.by)
    const actor = decision.via === 'mcp' ? `an agent for ${name}` : name
    if (decision.state === 'rejected') {
        return (
            <span>
                <span className="font-semibold text-danger">Rejected</span>
                <span>{` by ${actor} on `}</span>
                <code className="text-xs">{shortSha(decision.commit_sha)}</code>
                <span className="whitespace-pre-line">{`: ${decision.reason}`}</span>
            </span>
        )
    }
    if (decision.state === 'approved') {
        return (
            <span>
                <span className="font-semibold text-success">Accepted</span>
                <span>{` by ${actor} on `}</span>
                <code className="text-xs">{shortSha(decision.commit_sha)}</code>
                <span>{', '}</span>
                <TZLabel time={decision.at} />
            </span>
        )
    }
    return (
        <span>
            <span>{`${decision.via === 'mcp' ? `An agent for ${name}` : name} undid a decision on `}</span>
            <code className="text-xs">{shortSha(decision.commit_sha)}</code>
            <span>{', '}</span>
            <TZLabel time={decision.at} />
        </span>
    )
}
