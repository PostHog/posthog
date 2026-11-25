import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconExternal, IconPullRequest, IconRefresh, IconSidePanel } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSelect, LemonTabs, LemonTextArea, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { PRBrowserItemApi } from 'products/signals/frontend/generated/api.schemas'

import {
    PR_MONITORING_NOTE_MAX_CHARS,
    PRMonitoringFilter,
    PRStateFilter,
    capturePRAction,
    pullRequestsLogic,
} from '../../logics/pullRequestsLogic'
import { SignalReportStatus } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { SignalReportStatusBadge } from '../badges/SignalReportStatusBadge'
import { CardSkeleton } from '../cards/CardSkeleton'

function emptyPullRequestsMessage(filter: PRMonitoringFilter, stateFilter: PRStateFilter): string {
    if (stateFilter !== 'all') {
        return 'No pull requests match the current filters.'
    }
    if (filter === 'monitored') {
        return 'You have not monitored any of your recent pull requests yet.'
    }
    if (filter === 'unmonitored') {
        return 'All of your recent pull requests are already monitored.'
    }
    return "No recent pull requests in this project's connected repositories."
}

function pullRequestStateMeta(pr: PRBrowserItemApi): { label: string; color: string } {
    if (pr.state === 'merged') {
        return { label: 'Merged', color: 'text-[#8250df] dark:text-[#a371f7]' }
    }
    if (pr.state === 'closed') {
        return { label: 'Closed', color: 'text-muted' }
    }
    if (pr.draft) {
        return { label: 'Draft', color: 'text-muted' }
    }
    return { label: 'Open', color: 'text-success' }
}

function isRetryablePRStatus(reportStatus: SignalReportStatus | null): boolean {
    return reportStatus === SignalReportStatus.FAILED || reportStatus === SignalReportStatus.PENDING_INPUT
}

function PullRequestRowAction({
    prUrl,
    reportStatus,
    isMonitoring,
    isComposing,
    disabledReason,
    onToggleComposer,
}: {
    prUrl: string
    reportStatus: SignalReportStatus | null
    isMonitoring: boolean
    isComposing: boolean
    disabledReason: string | undefined
    onToggleComposer: (url: string) => void
}): JSX.Element {
    if (isRetryablePRStatus(reportStatus) && reportStatus) {
        return (
            <div className="flex items-center gap-1">
                <SignalReportStatusBadge status={reportStatus} />
                {isComposing ? null : (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        loading={isMonitoring}
                        disabled={isMonitoring && !disabledReason}
                        disabledReason={disabledReason}
                        data-attr="inbox-pr-retry"
                        onClick={() => onToggleComposer(prUrl)}
                    >
                        Retry
                    </LemonButton>
                )}
            </div>
        )
    }
    if (reportStatus) {
        return (
            <span className="mt-0.5">
                <SignalReportStatusBadge status={reportStatus} />
            </span>
        )
    }
    if (isComposing) {
        return <></>
    }
    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            loading={isMonitoring}
            disabled={isMonitoring && !disabledReason}
            disabledReason={disabledReason}
            data-attr="inbox-pr-monitor"
            onClick={() => onToggleComposer(prUrl)}
        >
            Monitor
        </LemonButton>
    )
}

function PullRequestComposer({
    prUrl,
    draftNote,
    isRetry,
    isMonitoring,
    disabledReason,
    onChangeNote,
    onCancel,
    onSubmit,
}: {
    prUrl: string
    draftNote: string
    isRetry: boolean
    isMonitoring: boolean
    disabledReason: string | undefined
    onChangeNote: (url: string, note: string) => void
    onCancel: () => void
    onSubmit: (url: string) => void
}): JSX.Element {
    const canSubmit = !isMonitoring && !disabledReason
    return (
        <div data-attr="inbox-pr-composer" className="flex flex-col gap-2 pl-6 pr-1.5">
            <LemonTextArea
                autoFocus
                stopPropagation
                minRows={2}
                maxRows={5}
                maxLength={PR_MONITORING_NOTE_MAX_CHARS}
                className="text-xs"
                value={draftNote}
                disabled={isMonitoring}
                aria-label="Optional monitoring guidance"
                data-attr="inbox-pr-note-input"
                placeholder="Optional: what metric or flow should PostHog watch? Leave blank to pick automatically."
                onChange={(value) => onChangeNote(prUrl, value)}
                onPressCmdEnter={() => {
                    if (canSubmit) {
                        onSubmit(prUrl)
                    }
                }}
                onKeyDown={(event) => {
                    if (event.key === 'Escape' && !isMonitoring) {
                        event.stopPropagation()
                        onCancel()
                    }
                }}
            />
            <div className="flex flex-wrap items-center justify-end gap-1.5">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    disabled={isMonitoring}
                    data-attr="inbox-pr-cancel-compose"
                    onClick={onCancel}
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="primary"
                    loading={isMonitoring}
                    disabled={isMonitoring && !disabledReason}
                    disabledReason={disabledReason}
                    data-attr="inbox-pr-submit-monitor"
                    onClick={() => onSubmit(prUrl)}
                >
                    {isRetry ? 'Retry research' : 'Start monitoring'}
                </LemonButton>
            </div>
        </div>
    )
}

function PullRequestRow({ pr }: { pr: PRBrowserItemApi }): JSX.Element {
    const { composingUrl, draftNotes, monitoringUrls } = useValues(pullRequestsLogic)
    const { closeComposer, monitorPR, openComposer, setDraftNote } = useActions(pullRequestsLogic)
    const { label, color } = pullRequestStateMeta(pr)
    const isMonitoring = Boolean(monitoringUrls[pr.url])
    const isComposing = composingUrl === pr.url
    const disabledReason =
        pr.monitoring_disabled_reason ??
        (pr.state === 'closed' ? 'Closed pull requests cannot be monitored' : undefined)
    const reportStatus = pr.report ? (pr.report.status as SignalReportStatus) : null
    const reportId = pr.report && reportStatus !== SignalReportStatus.FAILED ? pr.report.id : null

    const summary = (
        <>
            <span className={clsx('mt-0.5 flex shrink-0 items-center', color)}>
                <IconPullRequest className="size-3.5" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="line-clamp-2 break-words text-xs font-medium leading-snug text-primary">
                    {pr.title}
                </span>
                <span className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[11px] leading-tight text-tertiary">
                    <span className="truncate font-mono text-secondary">
                        {pr.repository}#{pr.number}
                    </span>
                    <span>·</span>
                    <span>{label}</span>
                    <span>·</span>
                    <TZLabel time={pr.created_at} />
                </span>
            </span>
        </>
    )

    return (
        <div
            data-attr="inbox-pr-row"
            className="flex flex-col gap-2 border-b border-primary py-2.5 pl-3 pr-1.5 transition-colors hover:bg-fill-highlight-50"
        >
            <div className="flex items-start gap-1.5">
                {reportId ? (
                    <Link
                        to={inboxReportDetailUrl(reportId, urls.inbox('monitoring'))}
                        data-attr="inbox-pr-open-report"
                        onClick={() => capturePRAction('open_report')}
                        className="flex min-w-0 flex-1 items-start gap-2.5 text-left no-underline hover:no-underline"
                    >
                        {summary}
                    </Link>
                ) : (
                    <div className="flex min-w-0 flex-1 items-start gap-2.5">{summary}</div>
                )}

                <div className="flex shrink-0 items-center gap-0.5">
                    <PullRequestRowAction
                        prUrl={pr.url}
                        reportStatus={reportStatus}
                        isMonitoring={isMonitoring}
                        isComposing={isComposing}
                        disabledReason={disabledReason}
                        onToggleComposer={(url) => (isComposing ? closeComposer() : openComposer(url))}
                    />
                    <LemonButton
                        icon={<IconExternal />}
                        size="xsmall"
                        type="tertiary"
                        to={pr.url}
                        targetBlank
                        tooltip="Open on GitHub"
                        aria-label={`Open ${pr.repository}#${pr.number} on GitHub`}
                        data-attr="inbox-pr-open-github"
                        onClick={() => capturePRAction('open_github')}
                    />
                </div>
            </div>
            {isComposing ? (
                <PullRequestComposer
                    prUrl={pr.url}
                    draftNote={draftNotes[pr.url] ?? ''}
                    isRetry={isRetryablePRStatus(reportStatus)}
                    isMonitoring={isMonitoring}
                    disabledReason={disabledReason}
                    onChangeNote={setDraftNote}
                    onCancel={closeComposer}
                    onSubmit={monitorPR}
                />
            ) : null}
        </div>
    )
}

function PullRequestsListBody(): JSX.Element {
    const { page, pageLoading, listError, filteredPRs, filter, stateFilter } = useValues(pullRequestsLogic)
    const { loadPullRequests } = useActions(pullRequestsLogic)

    if (!page) {
        if (listError) {
            return (
                <div className="p-3">
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPullRequests() }}>
                        Could not load your pull requests.
                    </LemonBanner>
                </div>
            )
        }
        return pageLoading ? (
            <div className="p-3">
                <CardSkeleton count={3} variant="rows" />
            </div>
        ) : (
            <></>
        )
    }

    if (!page.has_integration) {
        return (
            <div className="p-3.5 text-xs text-secondary">
                <Link to={urls.settings('project-integrations')}>Connect a GitHub integration</Link> to browse this
                project's repositories.
            </div>
        )
    }

    if (!page.github_login) {
        return (
            <div className="p-3.5 text-xs text-secondary">
                <Link to={urls.settings('user-personal-integrations')}>Connect your GitHub account</Link> so we can find
                your pull requests.
            </div>
        )
    }

    return (
        <>
            {listError ? (
                <div className="p-3">
                    <LemonBanner type="error" action={{ children: 'Retry', onClick: () => loadPullRequests() }}>
                        Could not refresh pull requests.
                    </LemonBanner>
                </div>
            ) : null}
            {filteredPRs.map((pr) => (
                <PullRequestRow key={pr.url} pr={pr} />
            ))}
            {filteredPRs.length === 0 ? (
                <p className="m-0 p-3.5 text-xs text-secondary">{emptyPullRequestsMessage(filter, stateFilter)}</p>
            ) : null}
        </>
    )
}

export function PullRequestsPanel({ className }: { className?: string }): JSX.Element {
    const { page, pageLoading, filter, stateFilter } = useValues(pullRequestsLogic)
    const { setFilter, setStateFilter, loadPullRequests, setPanelOpen } = useActions(pullRequestsLogic)

    return (
        <div
            role="complementary"
            aria-label="Pull requests"
            data-attr="inbox-pr-panel"
            className={clsx(
                'flex max-h-80 min-h-0 w-full shrink-0 flex-col overflow-hidden border-b border-primary bg-surface-primary @4xl/monitoring:h-full @4xl/monitoring:max-h-none @4xl/monitoring:w-96 @4xl/monitoring:border-b-0 @4xl/monitoring:border-l',
                className
            )}
        >
            <div className="flex h-9 shrink-0 items-center justify-between gap-1 border-b border-primary bg-surface-primary pl-3 pr-1.5">
                <div className="flex min-w-0 items-center gap-1.5">
                    <IconPullRequest className="size-3.5 shrink-0 text-secondary" />
                    <h2 className="m-0 truncate text-xs font-semibold text-primary">Pull requests</h2>
                    {page?.github_login ? (
                        <span className="truncate text-xs text-tertiary">@{page.github_login}</span>
                    ) : null}
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                    <LemonButton
                        icon={<IconRefresh />}
                        size="xsmall"
                        type="tertiary"
                        tooltip="Refresh pull requests"
                        aria-label="Refresh pull requests"
                        data-attr="inbox-pr-refresh"
                        loading={pageLoading}
                        onClick={() => loadPullRequests()}
                    />
                    <LemonButton
                        icon={<IconSidePanel />}
                        size="xsmall"
                        type="tertiary"
                        tooltip="Collapse panel"
                        aria-label="Collapse pull requests panel"
                        data-attr="inbox-pr-panel-collapse"
                        onClick={() => setPanelOpen(false)}
                    />
                </div>
            </div>

            <div className="flex shrink-0 items-center justify-between gap-2 border-b border-primary bg-surface-primary pl-3 pr-2">
                <LemonTabs<PRMonitoringFilter>
                    size="small"
                    activeKey={filter}
                    onChange={setFilter}
                    barClassName="before:hidden !mb-0"
                    data-attr="inbox-pr-filter-tabs"
                    tabs={[
                        { key: 'all', label: 'All', 'data-attr': 'inbox-pr-filter-all' },
                        { key: 'unmonitored', label: 'Unmonitored', 'data-attr': 'inbox-pr-filter-unmonitored' },
                        { key: 'monitored', label: 'Monitored', 'data-attr': 'inbox-pr-filter-monitored' },
                    ]}
                />
                <LemonSelect<PRStateFilter>
                    size="xsmall"
                    value={stateFilter}
                    onChange={setStateFilter}
                    data-attr="inbox-pr-state-filter"
                    options={[
                        { value: 'all', label: 'Any state' },
                        { value: 'open', label: 'Open' },
                        { value: 'merged', label: 'Merged' },
                    ]}
                />
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
                <PullRequestsListBody />
            </div>
        </div>
    )
}
