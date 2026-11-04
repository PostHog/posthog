import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import {
    IconArrowRight,
    IconBug,
    IconLogomark,
    IconPeople,
    IconSearch,
    IconThumbsDown,
    IconThumbsUp,
} from '@posthog/icons'
import { LemonButton, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import type { ErrorTrackingStoredIssueSummaryApi } from '../../generated/api.schemas'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssuePaneSectionHeader } from './IssuePaneSectionHeader'
import { issuePaneSectionsLogic } from './issuePaneSectionsLogic'
import { IssueSummaryFeedback, IssueSummaryView, issueSummaryLogic } from './issueSummaryLogic'

export interface IssueSummarySectionProps {
    view: IssueSummaryView
    summary: ErrorTrackingStoredIssueSummaryApi | null
    feedback: IssueSummaryFeedback | null
    open: boolean
    canManageAiSettings: boolean
    onToggle: () => void
    onRetry: () => void
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

/** Why there is no summary to open, as one line of the pane. */
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
        case 'not_generated':
            return <>No summary. Summaries are written when an issue is first seen.</>
        case 'restricted':
            return <>No summary. Summaries use event data you don't have access to.</>
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
                <>No summary. AI features are off for your organization. Ask an organization admin to turn them on.</>
            )
    }
}

export function IssueSummarySection({
    view,
    summary,
    feedback,
    open,
    canManageAiSettings,
    onToggle,
    onRetry,
    onFeedback,
}: IssueSummarySectionProps): JSX.Element | null {
    if (view === 'hidden') {
        return null
    }
    if (view !== 'ready') {
        return (
            // The left padding puts the name under the name of a section that has a toggle.
            <div
                className="flex min-h-[2rem] shrink-0 items-center gap-2 border-b py-1 pl-[1.625rem] pr-2 bg-surface-primary"
                data-attr="error-tracking-issue-summary"
            >
                <span className="flex shrink-0 items-center gap-1">
                    <IconLogomark className="text-lg" />
                    <span className="text-sm text-ai">Summary</span>
                </span>
                <span className="min-w-0 flex-1 text-xs text-secondary leading-snug">
                    <SummaryNote view={view} canManageAiSettings={canManageAiSettings} />
                </span>
                {view === 'failed' ? (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={onRetry}
                        data-attr="error-tracking-issue-summary-retry"
                    >
                        Try again
                    </LemonButton>
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
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const logic = issueSummaryLogic({ issueId })
    const { view, summary, feedback } = useValues(logic)
    const { loadSummary, sendFeedback } = useActions(logic)
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
            onToggle={() => setSummaryOpen(!summaryOpen)}
            onRetry={loadSummary}
            onFeedback={sendFeedback}
        />
    )
}
