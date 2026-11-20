import { IconExternal } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { PRBrowserOverviewApi } from 'products/signals/frontend/generated/api.schemas'

import { capturePRAction } from '../../logics/pullRequestsLogic'
import { safeHttpUrl } from '../../utils/reportPresentation'

export function PullRequestOverview({ overview }: { overview: PRBrowserOverviewApi }): JSX.Element {
    const pr = overview.pull_request
    return (
        <div className="p-5 flex flex-col gap-6 min-w-0">
            <div className="flex flex-wrap gap-2 items-center text-sm text-secondary">
                <span>
                    Opened by <strong>{pr.author}</strong>
                </span>
                <TZLabel time={pr.created_at} />
                <span>
                    · Updated <TZLabel time={pr.updated_at} />
                </span>
                <LemonButton
                    className="ml-auto"
                    type="secondary"
                    size="small"
                    to={pr.url}
                    targetBlank
                    icon={<IconExternal />}
                    onClick={() => capturePRAction('open_github')}
                >
                    Open in GitHub
                </LemonButton>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                <span className="break-all">
                    <code>{overview.head_branch}</code> → <code>{overview.base_branch}</code>
                </span>
                <span>{overview.changed_files} files changed</span>
                <span>
                    <span className="text-success">+{overview.additions}</span>{' '}
                    <span className="text-danger">−{overview.deletions}</span>
                </span>
            </div>
            {overview.has_conflicts && <LemonBanner type="warning">This PR has merge conflicts.</LemonBanner>}
            <section className="min-w-0">
                <h3 className="text-sm font-semibold mb-3">Description</h3>
                {overview.body ? (
                    <LemonMarkdown
                        disableImages="all"
                        className="break-words [overflow-wrap:anywhere] [&_pre]:whitespace-pre-wrap [&_table]:block [&_table]:overflow-auto"
                    >
                        {overview.body}
                    </LemonMarkdown>
                ) : (
                    <p className="text-secondary">No description provided.</p>
                )}
            </section>
            <section className="min-w-0">
                <h3 className="text-sm font-semibold mb-3">CI checks</h3>
                {!overview.checks_available ? (
                    <LemonBanner type="info">
                        CI checks are unavailable. Check the GitHub integration's permissions, or view checks on GitHub.
                    </LemonBanner>
                ) : overview.checks.length === 0 ? (
                    <p className="text-secondary">No checks reported for this PR.</p>
                ) : (
                    <ul className="list-none p-0 m-0 border border-primary rounded overflow-hidden">
                        {overview.checks.map((check, index) => {
                            const conclusion = check.conclusion ?? check.status
                            const url = safeHttpUrl(check.url)
                            return (
                                <li
                                    key={`${check.name}-${index}`}
                                    className="flex flex-wrap gap-2 items-center p-3 border-b last:border-b-0 border-primary"
                                >
                                    <span className="flex-1 min-w-0 break-words">
                                        {url ? (
                                            <Link
                                                to={url}
                                                target="_blank"
                                                onClick={() => capturePRAction('open_ci_check')}
                                            >
                                                {check.name}
                                            </Link>
                                        ) : (
                                            check.name
                                        )}
                                    </span>
                                    <LemonTag
                                        type={
                                            conclusion === 'success'
                                                ? 'success'
                                                : ['failure', 'timed_out', 'action_required'].includes(conclusion)
                                                  ? 'danger'
                                                  : 'default'
                                        }
                                    >
                                        {conclusion.replaceAll('_', ' ')}
                                    </LemonTag>
                                </li>
                            )
                        })}
                    </ul>
                )}
            </section>
        </div>
    )
}
