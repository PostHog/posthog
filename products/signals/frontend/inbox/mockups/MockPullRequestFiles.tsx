import { IconGitBranch } from '@posthog/icons'

import type { MockPullRequest } from './mockupData'
import { checksSummary } from './mockupFormat'

export function MockPullRequestFiles({ pullRequest }: { pullRequest: MockPullRequest }): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <p className="InboxMockup__muted flex items-center gap-1.5">
                <IconGitBranch className="size-3.5" aria-hidden />
                <span className="font-mono">{pullRequest.branch}</span>
                <span aria-hidden>·</span>
                <span>{checksSummary(pullRequest)}</span>
            </p>
            <ul className="InboxMockup__plainList">
                {pullRequest.files.map((file) => (
                    <li key={file.path} className="flex items-baseline justify-between gap-3">
                        <span className="min-w-0 truncate font-mono text-xs">{file.path}</span>
                        <span className="InboxMockup__muted shrink-0 tabular-nums">
                            +{file.additions} −{file.deletions}
                        </span>
                    </li>
                ))}
            </ul>
            {pullRequest.checks.failedName && (
                <p className="InboxMockup__risk">Failed: {pullRequest.checks.failedName}</p>
            )}
        </div>
    )
}
