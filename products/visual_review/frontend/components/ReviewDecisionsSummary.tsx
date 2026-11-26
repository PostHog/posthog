import { Link } from '@posthog/lemon-ui'

import type { RunProgressApi } from '../generated/api.schemas'
import { type DecisionFilter, type RejectionSummary, countChanges, shortSha } from '../lib/reviewDecisions'

// Each text is the only child of its element, so a page translator that replaces text nodes cannot break the line.
function RejectionLine({ rejections }: { rejections: RejectionSummary }): JSX.Element {
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

/**
 * What the newest run of a pull request inherits from its earlier runs: accepts whose pictures did not
 * change, and rejections that still block finalize.
 */
export function ReviewDecisionsSummary({
    progress,
    rejections,
    onShow,
}: {
    progress: RunProgressApi
    rejections: RejectionSummary
    onShow: (filter: DecisionFilter) => void
}): JSX.Element | null {
    const earlier = progress.approved_on_earlier_commits
    const needsReview = progress.needs_review
    if (earlier === 0 && rejections.count === 0) {
        return null
    }
    const one = earlier === 1
    return (
        <div className="flex flex-col gap-1 mb-4 text-sm" data-attr="visual-review-decisions-summary">
            {earlier > 0 && (
                <p className="m-0">
                    <span>
                        {`${countChanges(earlier)} ${one ? 'was' : 'were'} accepted on earlier commits of this PR and still ${one ? 'counts' : 'count'}, because ${one ? 'its pictures' : 'their pictures'} did not change. `}
                    </span>
                    <Link onClick={() => onShow('earlier')} data-attr="visual-review-show-earlier-accepts">
                        {one ? 'Show it' : 'Show them'}
                    </Link>
                    {needsReview > 0 && (
                        <span>{` ${needsReview} ${needsReview === 1 ? 'needs' : 'need'} review.`}</span>
                    )}
                </p>
            )}
            {rejections.count > 0 && (
                <p className="m-0">
                    <RejectionLine rejections={rejections} />
                    <Link onClick={() => onShow('rejected')} data-attr="visual-review-show-rejections">
                        {rejections.count === 1 ? 'Show it' : 'Show them'}
                    </Link>
                </p>
            )}
        </div>
    )
}
