import { Link } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import type { HeadRunApi } from '../generated/api.schemas'
import { type OlderRunSituation, shortSha } from '../lib/reviewDecisions'

/** Where decisions made on an older run of a ledger-mode pull request count, by how its newest run stands. */
export function OlderRunBanner({
    situation,
    headRun,
    prNumber,
    commitSha,
    headRunUrl,
}: {
    situation: OlderRunSituation
    headRun: HeadRunApi
    prNumber: number | null
    commitSha: string
    headRunUrl: string
}): JSX.Element {
    const viewNewest = (
        <Link to={headRunUrl} className="font-semibold" data-attr="visual-review-view-newest-run">
            View newest run
        </Link>
    )
    return (
        <LemonBanner type="warning" className="mb-4">
            {situation === 'head_processing' ? (
                <>
                    A newer commit of this PR is being checked. Decisions you make here count on it where the pictures
                    are the same.
                </>
            ) : situation === 'head_finalized' ? (
                <>
                    PR #{prNumber} was finalized on <code>{shortSha(headRun.commit_sha)}</code>. Decisions on this pull
                    request are fixed until the next push. {viewNewest}
                </>
            ) : (
                <>
                    This is an older commit of PR #{prNumber} (<code>{shortSha(commitSha)}</code>). Decisions you make
                    here count on the newest commit (<code>{shortSha(headRun.commit_sha)}</code>) where the pictures are
                    the same. {viewNewest}
                </>
            )}
        </LemonBanner>
    )
}
