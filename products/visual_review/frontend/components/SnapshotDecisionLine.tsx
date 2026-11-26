import { TZLabel } from 'lib/components/TZLabel'

import type { EarlierSnapshotDecisionApi, SnapshotApi, SnapshotDecisionApi } from '../generated/api.schemas'
import { personName, shortSha } from '../lib/reviewDecisions'

const EARLIER_CHANGE_TEXT: Record<EarlierSnapshotDecisionApi['changed'], string> = {
    after: 'The after picture changed since.',
    before: 'The before picture changed since, because the default branch or the PR below changed it.',
    both: 'Both pictures changed since.',
}

function Commit({ sha }: { sha: string }): JSX.Element {
    return <code className="text-xs">{shortSha(sha)}</code>
}

function CurrentDecision({ decision }: { decision: SnapshotDecisionApi }): JSX.Element {
    const name = personName(decision.by)
    if (decision.state === 'rejected') {
        return (
            <span>
                <span className="font-semibold text-danger">Rejected</span> by {name} on{' '}
                <Commit sha={decision.commit_sha} />: {decision.reason}
            </span>
        )
    }
    if (decision.state === 'approved') {
        return (
            <span>
                <span className="font-semibold text-success">Accepted</span> by{' '}
                {decision.via === 'mcp' ? `an agent for ${name}` : name} on <Commit sha={decision.commit_sha} />,{' '}
                <TZLabel time={decision.at} />
            </span>
        )
    }
    return (
        <span>
            {name} undid a decision on <Commit sha={decision.commit_sha} />, <TZLabel time={decision.at} />
        </span>
    )
}

function EarlierDecision({ decision }: { decision: EarlierSnapshotDecisionApi }): JSX.Element | null {
    if (decision.state === 'cleared') {
        return null
    }
    const verb = decision.state === 'rejected' ? 'rejected' : 'accepted'
    return (
        <span>
            {personName(decision.by)} {verb} an earlier picture of this story on <Commit sha={decision.commit_sha} />.{' '}
            {EARLIER_CHANGE_TEXT[decision.changed]}
        </span>
    )
}

/** Who decided on the pictures this story shows, and whether a decision here counts on the newest run. */
export function SnapshotDecisionLine({
    snapshot,
    headPictureLine,
}: {
    snapshot: SnapshotApi
    headPictureLine: string | null
}): JSX.Element | null {
    const { decision, earlier_decision } = snapshot
    if (!decision && !earlier_decision && !headPictureLine) {
        return null
    }
    return (
        <div className="flex flex-col gap-1 mb-4 text-sm text-secondary" data-attr="visual-review-decision-line">
            {decision ? (
                <CurrentDecision decision={decision} />
            ) : earlier_decision ? (
                <EarlierDecision decision={earlier_decision} />
            ) : null}
            {headPictureLine && <span>{headPictureLine}</span>}
        </div>
    )
}
