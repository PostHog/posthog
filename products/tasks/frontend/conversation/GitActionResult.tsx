import { IconCheckCircle, IconCommit, IconExternal, IconPullRequest } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'
import { JSX } from 'react'

import { GitActionType } from './GitActionMessage'

/**
 * Ported from
 * apps/code/src/renderer/features/sessions/components/GitActionResult.tsx.
 *
 * The reference component drives its content from live tRPC git queries
 * (latest commit, repo info) and an "open external URL" mutation. This is a
 * read-only transcript, so those live fetches are dropped: the result line is
 * reconstructed from plain props captured in the log, and the "open on GitHub"
 * affordance is rendered as a disabled button.
 */

export interface GitActionCommitInfo {
    shortSha: string
    message: string
}

export interface GitActionRepoInfo {
    currentBranch?: string
    compareUrl?: string | null
}

interface GitActionResultProps {
    actionType: GitActionType
    commitInfo?: GitActionCommitInfo | null
    repoInfo?: GitActionRepoInfo | null
}

export function GitActionResult({ actionType, commitInfo, repoInfo }: GitActionResultProps): JSX.Element | null {
    const showCommit = commitInfo != null
    const showPrLink = repoInfo?.compareUrl != null

    if (!showCommit && !showPrLink) {
        return null
    }

    return (
        <div className="mt-3 rounded-lg border border-success bg-success-highlight p-3">
            <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                    <IconCheckCircle className="text-success" style={{ fontSize: 16 }} />
                    <span className="font-medium text-sm text-success">{getCompletionLabel(actionType)}</span>
                </div>

                {showCommit && commitInfo && (
                    <div className="mt-1 flex items-center gap-2">
                        <IconCommit className="text-muted" style={{ fontSize: 14 }} />
                        <span className="font-mono text-[13px] text-muted">{commitInfo.shortSha}</span>
                        <span className="max-w-[200px] overflow-hidden whitespace-nowrap text-ellipsis text-[13px] text-muted">
                            {commitInfo.message}
                        </span>
                        <LemonTag type="success">Latest</LemonTag>
                    </div>
                )}

                {showPrLink && repoInfo?.compareUrl && (
                    <div className="mt-1 flex items-center gap-2">
                        <IconPullRequest className="text-accent" style={{ fontSize: 14 }} />
                        <span className="font-medium text-[13px]">{repoInfo.currentBranch}</span>
                        <LemonButton
                            size="small"
                            icon={<IconExternal />}
                            disabledReason="Opening links is not available in a read-only transcript"
                        >
                            Open on GitHub
                        </LemonButton>
                    </div>
                )}
            </div>
        </div>
    )
}

function getCompletionLabel(actionType: GitActionType): string {
    switch (actionType) {
        case 'commit-push':
            return 'Changes committed & pushed'
        case 'push':
            return 'Changes pushed'
        case 'pull':
            return 'Changes pulled'
        case 'sync':
            return 'Repository synced'
        case 'publish':
            return 'Branch published'
        case 'create-pr':
            return 'Ready for pull request'
        default:
            return 'Git action completed'
    }
}
