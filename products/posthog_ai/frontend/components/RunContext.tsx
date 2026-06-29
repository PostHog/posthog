import { memo } from 'react'

import { IconGitBranch } from '@posthog/icons'

/**
 * Pre-turn header for a sandbox coding run: a one-line "Working on <repo> · <branch> → <base>"
 * summary. Plain props, `React.memo`'d — `branch` is required, so the caller decides whether to mount
 * it (only when a run reports git context). This complements — does not replace — the
 * `_posthog/progress` provisioning steps.
 */
export const RunContext = memo(function RunContext({
    branch,
    baseBranch,
    repo,
}: {
    branch: string
    baseBranch?: string
    repo?: string
}): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 px-3 py-1 text-xs text-muted" data-attr="max-sandbox-run-context">
            <IconGitBranch className="size-3.5 shrink-0" />
            <span className="min-w-0 truncate">
                Working on{' '}
                {repo ? (
                    <>
                        <span className="font-medium">{repo}</span>
                        {' · '}
                    </>
                ) : null}
                <span className="font-mono">{branch}</span>
                {baseBranch ? (
                    <>
                        {' → '}
                        <span className="font-mono">{baseBranch}</span>
                    </>
                ) : null}
            </span>
        </div>
    )
})
