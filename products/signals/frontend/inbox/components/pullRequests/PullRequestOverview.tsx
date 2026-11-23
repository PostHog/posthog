import {
    IconCheckCircle,
    IconCircleDashed,
    IconDocument,
    IconExternal,
    IconSpinner,
    IconWarning,
    IconX,
} from '@posthog/icons'
import { LemonBanner, Link } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import type { PRBrowserOverviewApi, PullRequestCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { capturePRAction } from '../../logics/pullRequestsLogic'
import { safeHttpUrl } from '../../utils/reportPresentation'
import { DetailSection } from '../detail/DetailSection'

function checkStatusMeta(check: PullRequestCheckApi): { icon: JSX.Element; label: string; className: string } {
    if (check.status !== 'completed') {
        return {
            icon: <IconSpinner className="animate-spin motion-reduce:animate-none" />,
            label: check.status === 'queued' ? 'Queued' : 'Running',
            className: 'text-warning',
        }
    }
    switch (check.conclusion) {
        case 'success':
            return { icon: <IconCheckCircle />, label: 'Passed', className: 'text-success' }
        case 'failure':
        case 'timed_out':
        case 'action_required':
        case 'startup_failure':
            return { icon: <IconWarning />, label: 'Failed', className: 'text-danger' }
        case 'cancelled':
            return { icon: <IconX />, label: 'Cancelled', className: 'text-muted' }
        default:
            return { icon: <IconCircleDashed />, label: 'Skipped', className: 'text-tertiary' }
    }
}

export function PullRequestOverview({ overview }: { overview: PRBrowserOverviewApi }): JSX.Element {
    return (
        <div className="flex min-w-0 flex-col">
            {overview.has_conflicts ? (
                <div className="border-b border-primary px-3.5 py-2.5">
                    <LemonBanner type="warning">This pull request has merge conflicts.</LemonBanner>
                </div>
            ) : null}

            <div className="border-b border-primary px-3.5 py-3">
                <DetailSection icon={<IconCheckCircle />} title="CI checks" collapsible>
                    {!overview.checks_available ? (
                        <LemonBanner type="info">
                            CI checks are unavailable. Check the GitHub integration's permissions, or view checks on
                            GitHub.
                        </LemonBanner>
                    ) : overview.checks.length === 0 ? (
                        <p className="m-0 text-xs text-secondary">No checks reported for this pull request.</p>
                    ) : (
                        <ul className="m-0 list-none divide-y divide-border overflow-hidden rounded border border-primary bg-surface-primary p-0">
                            {overview.checks.map((check, index) => {
                                const meta = checkStatusMeta(check)
                                const url = safeHttpUrl(check.url)
                                const content = (
                                    <>
                                        <span
                                            aria-hidden
                                            className={`flex shrink-0 items-center [&_svg]:size-3.5 ${meta.className}`}
                                        >
                                            {meta.icon}
                                        </span>
                                        <span
                                            className="min-w-0 flex-1 truncate text-xs font-medium text-primary"
                                            title={check.name}
                                        >
                                            {check.name}
                                        </span>
                                        <span className="shrink-0 text-[11px] text-tertiary">{meta.label}</span>
                                        {url ? (
                                            <IconExternal className="size-3 shrink-0 text-tertiary opacity-60 group-hover:opacity-100" />
                                        ) : null}
                                    </>
                                )
                                return (
                                    <li key={`${check.name}-${index}`}>
                                        {url ? (
                                            <Link
                                                to={url}
                                                target="_blank"
                                                onClick={() => capturePRAction('open_ci_check')}
                                                className="group flex min-w-0 items-center gap-2 px-2.5 py-2 text-primary no-underline transition-colors hover:bg-fill-highlight-50 hover:text-primary"
                                            >
                                                {content}
                                            </Link>
                                        ) : (
                                            <span className="flex min-w-0 items-center gap-2 px-2.5 py-2">
                                                {content}
                                            </span>
                                        )}
                                    </li>
                                )
                            })}
                        </ul>
                    )}
                </DetailSection>
            </div>

            <div className="px-3.5 py-3">
                <DetailSection icon={<IconDocument />} title="Description" collapsible>
                    {overview.body ? (
                        <LemonMarkdown
                            disableImages="all"
                            className="break-words text-xs [overflow-wrap:anywhere] [&_pre]:whitespace-pre-wrap [&_table]:block [&_table]:overflow-auto"
                        >
                            {overview.body}
                        </LemonMarkdown>
                    ) : (
                        <p className="m-0 text-xs text-secondary">No description provided.</p>
                    )}
                </DetailSection>
            </div>
        </div>
    )
}
