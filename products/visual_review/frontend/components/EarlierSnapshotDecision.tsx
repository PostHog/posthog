import type { EarlierSnapshotDecisionApi } from '../generated/api.schemas'
import { personName, shortSha } from '../lib/reviewDecisions'

const EARLIER_CHANGE_TEXT: Record<EarlierSnapshotDecisionApi['changed'], string> = {
    after: 'The after picture changed since.',
    before: 'The before picture changed since, because the default branch or the PR below changed it.',
    both: 'Both pictures changed since.',
}

export function EarlierSnapshotDecision({ decision }: { decision: EarlierSnapshotDecisionApi }): JSX.Element | null {
    if (decision.state === 'cleared') {
        return null
    }
    const verb = decision.state === 'rejected' ? 'rejected' : 'accepted'
    return (
        <span>
            <span>{`${personName(decision.by)} ${verb} an earlier picture of this story on `}</span>
            <code className="text-xs">{shortSha(decision.commit_sha)}</code>
            <span>{`. ${EARLIER_CHANGE_TEXT[decision.changed]}`}</span>
        </span>
    )
}
