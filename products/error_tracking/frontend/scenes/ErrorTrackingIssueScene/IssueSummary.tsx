import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowRight, IconBug, IconPeople, IconSearch, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { organizationLogic } from 'scenes/organizationLogic'
import { AIAccessRequest } from 'scenes/settings/organization/AIAccessRequest'
import { urls } from 'scenes/urls'

import type { ErrorTrackingStoredIssueSummaryApi } from '../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../utils'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssuePaneSectionHeader } from './IssuePaneSectionHeader'
import { IssuePaneSectionName } from './IssuePaneSectionName'
import { issuePaneSectionsLogic } from './issuePaneSectionsLogic'
import { IssueSummaryFeedback, IssueSummaryView, issueSummaryLogic } from './issueSummaryLogic'

export interface IssueSummarySectionProps {
    view: IssueSummaryView
    summary: ErrorTrackingStoredIssueSummaryApi | null
    feedback: IssueSummaryFeedback | null
    open: boolean
    canManageAiSettings: boolean
    loading: boolean
    // Set when the person may not start a summary, which needs editor access to error tracking.
    summarizeDisabledReason?: string | null
    onToggle: () => void
    onRetry: () => void
    onSummarize: () => void
    onFeedback: (feedback: IssueSummaryFeedback) => void
}

function SummaryField({
    icon,
    label,
    tag,
    emphasis = false,
    children,
}: {
    icon: JSX.Element
    label: string
    tag?: JSX.Element
    emphasis?: boolean
    children: string
}): JSX.Element {
    return (
        <div className="grid gap-x-3 gap-y-0.5 px-2 py-1.5 border-b @xl:grid-cols-[11rem_1fr]">
            <dt className="flex flex-wrap items-center gap-1 text-xs font-semibold text-secondary @xl:items-start @xl:pt-0.5">
                <span className="flex shrink-0 text-sm">{icon}</span>
                <span>{label}</span>
                {tag}
            </dt>
            <dd className={clsx('m-0 text-sm leading-snug', emphasis && 'font-semibold')}>{children}</dd>
        </div>
    )
}

function SummaryNote({
    view,
    canManageAiSettings,
}: {
    view: Exclude<IssueSummaryView, 'hidden' | 'ready'>
    canManageAiSettings: boolean
}): JSX.Element {
    switch (view) {
        case 'failed':
            return <>Couldn't load the summary.</>
        case 'writing':
            return <>No summary yet. Summaries take a minute to write after an issue is first seen.</>
        case 'not_generated':
            return <>No summary to show for this issue.</>
        case 'restricted':
            return <>No summary. Summaries use event data you don't have access to.</>
        case 'setting_off':
            return (
                <>
                    No summary. Issue summaries are off for this project.{' '}
                    <Link
                        to={urls.settings('environment-error-tracking', 'error-tracking-ai-features')}
                        className="whitespace-nowrap"
                        data-attr="error-tracking-issue-summary-settings"
                    >
                        Manage AI features
                    </Link>
                </>
            )
        case 'out_of_credits':
            return canManageAiSettings ? (
                <>
                    No summary. Your organization reached its AI credits limit.{' '}
                    <Link
                        to={urls.organizationBilling()}
                        className="whitespace-nowrap"
                        data-attr="error-tracking-issue-summary-billing"
                    >
                        Manage billing
                    </Link>
                </>
            ) : (
                <>No summary. Your organization reached its AI credits limit. Ask an organization admin to raise it.</>
            )
        case 'rate_limited':
            return <>This project asked for too many summaries. Try again in a few minutes.</>
        case 'in_progress':
            return <>A summary is being written. Check again in a minute.</>
        case 'no_exception':
            return <>No summary. This issue has no stack trace to summarize.</>
        case 'summarize_failed':
            return <>Couldn't write the summary.</>
        case 'ai_not_approved':
            return canManageAiSettings ? (
                <>
                    No summary. AI features are off for your organization.{' '}
                    <Link
                        to={urls.settings('organization-details', 'organization-ai-consent')}
                        className="whitespace-nowrap"
                        data-attr="error-tracking-issue-summary-ai-settings"
                    >
                        Manage AI settings
                    </Link>
                </>
            ) : (
                <>
                    No summary. AI features are off for your organization.
                    <div className="mt-1">
                        <AIAccessRequest />
                    </div>
                </>
            )
    }
}

export function IssueSummarySection({
    view,
    summary,
    feedback,
    open,
    canManageAiSettings,
    loading,
    summarizeDisabledReason,
    onToggle,
    onRetry,
    onSummarize,
    onFeedback,
}: IssueSummarySectionProps): JSX.Element | null {
    if (view === 'hidden') {
        return null
    }
    if (view !== 'ready') {
        return (
            // The left padding puts the name under the name of a section that has a toggle. It is the header's
            // pl-0.5 plus the toggle's chevron: an xsmall LemonButton's horizontal padding, icon and gap.
            <div
                className="flex min-h-[2rem] shrink-0 items-center gap-2 border-b py-1 pl-[1.625rem] pr-2 bg-surface-primary"
                data-attr="error-tracking-issue-summary"
            >
                <IssuePaneSectionName name="Summary" />
                <div className="min-w-0 flex-1 text-xs text-secondary leading-snug">
                    <SummaryNote view={view} canManageAiSettings={canManageAiSettings} />
                </div>
                {view === 'failed' || view === 'writing' || view === 'in_progress' ? (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={onRetry}
                        loading={loading}
                        data-attr={
                            view === 'failed'
                                ? 'error-tracking-issue-summary-retry'
                                : 'error-tracking-issue-summary-check-again'
                        }
                    >
                        {view === 'failed' ? 'Try again' : 'Check again'}
                    </LemonButton>
                ) : view === 'not_generated' || view === 'summarize_failed' || view === 'rate_limited' ? (
                    <div className="flex shrink-0 items-center gap-2">
                        <span className="text-xs text-secondary whitespace-nowrap">Uses AI credits</span>
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={onSummarize}
                            loading={loading}
                            disabledReason={summarizeDisabledReason}
                            data-attr={
                                view === 'not_generated'
                                    ? 'error-tracking-issue-summary-summarize'
                                    : 'error-tracking-issue-summary-summarize-retry'
                            }
                        >
                            {view === 'not_generated' ? 'Summarize' : 'Try again'}
                        </LemonButton>
                    </div>
                ) : null}
            </div>
        )
    }
    if (!summary) {
        return null
    }
    return (
        // The section never takes more than 40% of the pane, so the exception card keeps its room.
        <div className="min-h-0 max-h-[40%] flex flex-col bg-surface-primary" data-attr="error-tracking-issue-summary">
            <IssuePaneSectionHeader
                name="Summary"
                open={open}
                onToggle={onToggle}
                preview={open ? null : summary.what_happened}
                dataAttr="error-tracking-issue-summary-toggle"
                trailing={
                    open ? (
                        <div className="flex items-center gap-0.5 shrink-0">
                            <LemonButton
                                size="xsmall"
                                icon={<IconThumbsUp />}
                                active={feedback === 'good'}
                                disabledReason={feedback ? 'Thanks for the feedback' : undefined}
                                tooltip="This summary is helpful"
                                onClick={() => onFeedback('good')}
                                data-attr="error-tracking-issue-summary-feedback-good"
                            />
                            <LemonButton
                                size="xsmall"
                                icon={<IconThumbsDown />}
                                active={feedback === 'bad'}
                                disabledReason={feedback ? 'Thanks for the feedback' : undefined}
                                tooltip="This summary is wrong or not helpful"
                                onClick={() => onFeedback('bad')}
                                data-attr="error-tracking-issue-summary-feedback-bad"
                            />
                        </div>
                    ) : null
                }
            />
            {open ? (
                <div className="@container min-h-0 overflow-y-auto">
                    <dl className="m-0">
                        <SummaryField icon={<IconBug />} label="What happened" emphasis>
                            {summary.what_happened}
                        </SummaryField>
                        {summary.likely_cause ? (
                            <SummaryField
                                icon={<IconSearch />}
                                label="Likely cause"
                                tag={
                                    <LemonTag size="small" type="muted">
                                        Hypothesis
                                    </LemonTag>
                                }
                            >
                                {summary.likely_cause}
                            </SummaryField>
                        ) : null}
                        <SummaryField icon={<IconPeople />} label="Who is affected">
                            {summary.who_is_affected}
                        </SummaryField>
                        <SummaryField icon={<IconArrowRight />} label="Next step">
                            {summary.suggested_next_step}
                        </SummaryField>
                    </dl>
                    <div className="px-2 py-1 text-xs text-muted">
                        Generated <TZLabel time={summary.generated_at} />
                    </div>
                </div>
            ) : null}
        </div>
    )
}

export function IssueSummary(): JSX.Element | null {
    const { issueId, issue } = useValues(errorTrackingIssueSceneLogic)
    const logic = issueSummaryLogic({ issueId, firstSeen: issue?.first_seen ?? null })
    const { view, summary, feedback, summaryResponseLoading } = useValues(logic)
    const { loadSummary, summarize, sendFeedback } = useActions(logic)
    const { summaryOpen } = useValues(issuePaneSectionsLogic)
    const { setSummaryOpen } = useActions(issuePaneSectionsLogic)
    const { isAdminOrOwner } = useValues(organizationLogic)
    return (
        <IssueSummarySection
            view={view}
            summary={summary}
            feedback={feedback}
            open={summaryOpen}
            canManageAiSettings={!!isAdminOrOwner}
            loading={summaryResponseLoading}
            summarizeDisabledReason={errorTrackingEditAccessDisabledReason()}
            onToggle={() => setSummaryOpen(!summaryOpen)}
            onRetry={loadSummary}
            onSummarize={summarize}
            onFeedback={sendFeedback}
        />
    )
}
