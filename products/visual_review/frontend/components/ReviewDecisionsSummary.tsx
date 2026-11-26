import { Link } from '@posthog/lemon-ui'

import type { RunProgressApi } from '../generated/api.schemas'
import { type DecisionFilter, type RejectionSummary, countChanges, shortSha } from '../lib/reviewDecisions'

function RejectionLine({ rejections }: { rejections: RejectionSummary }): JSX.Element {
    const { count, rejecter, commitSha } = rejections
    const one = count === 1
    if (!rejecter) {
        return (
            <>
                {count} changes are rejected. They block finalize until their pictures change or the rejections are
                undone.
            </>
        )
    }
    return (
        <>
            {rejecter} rejected {countChanges(count)}
            {commitSha && (
                <>
                    {' '}
                    on <code className="text-xs">{shortSha(commitSha)}</code>
                </>
            )}
            . {one ? 'It blocks' : 'They block'} finalize until the {one ? 'picture changes' : 'pictures change'} or{' '}
            {rejecter} undoes {one ? 'it' : 'them'}.
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
    return (
        <div className="flex flex-col gap-1 mb-4 text-sm" data-attr="visual-review-decisions-summary">
            {earlier > 0 && (
                <p className="m-0">
                    {countChanges(earlier)} {earlier === 1 ? 'was' : 'were'} accepted on earlier commits of this PR and
                    still {earlier === 1 ? 'counts' : 'count'}, because{' '}
                    {earlier === 1 ? 'its pictures' : 'their pictures'} did not change.
                    {needsReview > 0 && ` ${needsReview} ${needsReview === 1 ? 'needs' : 'need'} review.`}{' '}
                    <Link onClick={() => onShow('earlier')} data-attr="visual-review-show-earlier-accepts">
                        Show {earlier === 1 ? 'it' : 'them'}
                    </Link>
                </p>
            )}
            {rejections.count > 0 && (
                <p className="m-0">
                    <RejectionLine rejections={rejections} />{' '}
                    <Link onClick={() => onShow('rejected')} data-attr="visual-review-show-rejections">
                        Show {rejections.count === 1 ? 'it' : 'them'}
                    </Link>
                </p>
            )}
        </div>
    )
}
