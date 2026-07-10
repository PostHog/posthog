import { memo } from 'react'

import { IconCheckCircle, IconExternal, IconPullRequest } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

/**
 * Post-turn "Pull request opened" card for a sandbox coding run — the web port of PostHog Code's
 * `GitActionResult`, adapted to LemonUI. Plain props, `React.memo`'d — `prUrl` is required, so the
 * caller decides whether to mount it (only once a run has opened a PR and is no longer thinking).
 * Frontend-only: it shows the link + branch, no diff stats (those need a backend wire field; see the
 * logic's follow-ups).
 */
export const PullRequestCard = memo(function PullRequestCard({
    prUrl,
    branch,
}: {
    prUrl: string
    branch?: string
}): JSX.Element {
    return (
        <div
            className="flex flex-col gap-2 rounded-lg border border-success bg-success-highlight p-3"
            data-attr="max-sandbox-pr-card"
        >
            <div className="flex items-center gap-2">
                <IconCheckCircle className="size-4 shrink-0 text-success" />
                <span className="text-sm font-medium text-success">Pull request opened</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <span className="flex items-center gap-1.5 text-xs text-muted">
                    <IconPullRequest className="size-3.5 shrink-0" />
                    {branch ? <span className="font-mono">{branch}</span> : null}
                </span>
                <LemonButton type="secondary" size="xsmall" icon={<IconExternal />} to={prUrl} targetBlank>
                    Open on GitHub
                </LemonButton>
            </div>
        </div>
    )
})
