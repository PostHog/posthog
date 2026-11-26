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
    // Each text is the only child of its element, so a page translator that replaces text nodes cannot break the banner.
    return (
        <LemonBanner type="warning" className="mb-4">
            {situation === 'head_processing' ? (
                <span>
                    A newer commit of this PR is being checked. Decisions you make here count on it where the pictures
                    are the same.
                </span>
            ) : situation === 'head_finalized' ? (
                <>
                    <span>{`PR #${prNumber} was finalized on `}</span>
                    <code>{shortSha(headRun.commit_sha)}</code>
                    <span>{'. Decisions on this pull request are fixed until the next push. '}</span>
                    {viewNewest}
                </>
            ) : (
                <>
                    <span>{`This is an older commit of PR #${prNumber} (`}</span>
                    <code>{shortSha(commitSha)}</code>
                    <span>). Decisions you make here count on the newest commit (</span>
                    <code>{shortSha(headRun.commit_sha)}</code>
                    <span>{') where the pictures are the same. '}</span>
                    {viewNewest}
                </>
            )}
        </LemonBanner>
    )
}
