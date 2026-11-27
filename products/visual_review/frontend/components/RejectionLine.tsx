import { type RejectionSummary, countChanges, shortSha } from '../lib/reviewDecisions'

// Each text is the only child of its element, so a page translator that replaces text nodes cannot break the line.
export function RejectionLine({ rejections }: { rejections: RejectionSummary }): JSX.Element {
    const { count, rejecter, byAgent, commitSha } = rejections
    if (!rejecter) {
        return (
            <span>
                {`${count} changes are rejected. They block finalize until their pictures change or the rejections are undone. `}
            </span>
        )
    }
    const one = count === 1
    const who = byAgent ? `An agent for ${rejecter}` : rejecter
    return (
        <>
            <span>{`${who} rejected ${countChanges(count)}${commitSha ? ' on ' : ''}`}</span>
            {commitSha && <code className="text-xs">{shortSha(commitSha)}</code>}
            <span>
                {`. ${one ? 'It blocks' : 'They block'} finalize until the ${one ? 'picture changes' : 'pictures change'} or ${rejecter} undoes ${one ? 'it' : 'them'}. `}
            </span>
        </>
    )
}
