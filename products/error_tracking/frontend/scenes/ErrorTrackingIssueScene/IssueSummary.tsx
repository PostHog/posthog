import { useActions, useValues } from 'kea'

import { IconLogomark, IconRefresh, IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { dayjs } from 'lib/dayjs'

import type { ErrorTrackingIssueSummaryApi } from '../../generated/api.schemas'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssueSummaryFeedback, IssueSummaryView, issueSummaryLogic } from './issueSummaryLogic'

export interface IssueSummarySectionProps {
    view: IssueSummaryView
    summary: ErrorTrackingIssueSummaryApi | null
    regenerating: boolean
    feedback: IssueSummaryFeedback | null
    onRegenerate: () => void
    onRetry: () => void
    onFeedback: (feedback: IssueSummaryFeedback) => void
}

function SummaryField({ label, children }: { label: string; children: string }): JSX.Element {
    return (
        <div>
            <div className="text-xs font-semibold text-secondary">{label}</div>
            <p className="m-0 text-sm leading-snug">{children}</p>
        </div>
    )
}

export function IssueSummarySection({
    view,
    summary,
    regenerating,
    feedback,
    onRegenerate,
    onRetry,
    onFeedback,
}: IssueSummarySectionProps): JSX.Element | null {
    if (view === 'hidden') {
        return null
    }
    // Generation runs at most once a day per issue, so a regenerate inside that window would do nothing.
    const regenerateDisabledReason =
        summary && dayjs().diff(dayjs(summary.generated_at), 'hour') < 24
            ? 'A summary can be regenerated once a day'
            : undefined
    return (
        // The section never takes more than 40% of the pane, so the exception card keeps its room.
        <div className="min-h-0 max-h-[40%] flex flex-col bg-surface-primary" data-attr="error-tracking-issue-summary">
            <div className="flex justify-between h-[2rem] items-center w-full px-2 border-b shrink-0 gap-2">
                <div className="flex items-center gap-1 text-lg h-full min-w-0">
                    <IconLogomark />
                    <span className="text-sm text-ai truncate">Summary</span>
                </div>
                {view === 'ready' && (
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
                        <LemonButton
                            size="xsmall"
                            icon={<IconRefresh />}
                            loading={regenerating}
                            disabledReason={regenerating ? 'Regenerating the summary' : regenerateDisabledReason}
                            tooltip="Regenerate the summary"
                            onClick={onRegenerate}
                            data-attr="error-tracking-issue-summary-regenerate"
                        />
                    </div>
                )}
            </div>
            {view === 'ready' && summary ? (
                <div className="min-h-0 overflow-y-auto px-2 py-2 flex flex-col gap-2">
                    <SummaryField label="What happened">{summary.what_happened}</SummaryField>
                    {summary.likely_cause ? (
                        <SummaryField label="Likely cause (hypothesis)">{summary.likely_cause}</SummaryField>
                    ) : null}
                    <SummaryField label="Who is affected">{summary.who_is_affected}</SummaryField>
                    <SummaryField label="Next step">{summary.suggested_next_step}</SummaryField>
                    <div className="text-xs text-muted">
                        Generated <TZLabel time={summary.generated_at} />
                    </div>
                </div>
            ) : view === 'generating' ? (
                <div className="px-2 py-2 flex flex-col gap-2" aria-busy="true">
                    <span className="text-sm text-secondary">Summarizing this issue…</span>
                    <LemonSkeleton className="h-3 w-full" />
                    <LemonSkeleton className="h-3 w-4/5" />
                    <LemonSkeleton className="h-3 w-3/5" />
                </div>
            ) : (
                <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                    <span className="text-sm text-secondary min-w-0">
                        {view === 'timed_out'
                            ? 'The summary is taking longer than usual.'
                            : "Couldn't load the summary."}
                    </span>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={onRetry}
                        data-attr="error-tracking-issue-summary-retry"
                    >
                        Try again
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

export function IssueSummary(): JSX.Element | null {
    const { issueId } = useValues(errorTrackingIssueSceneLogic)
    const logic = issueSummaryLogic({ issueId })
    const { view, summary, regenerating, feedback } = useValues(logic)
    const { regenerateSummary, loadSummary, sendFeedback } = useActions(logic)
    return (
        <IssueSummarySection
            view={view}
            summary={summary}
            regenerating={regenerating}
            feedback={feedback}
            onRegenerate={regenerateSummary}
            onRetry={loadSummary}
            onFeedback={sendFeedback}
        />
    )
}
