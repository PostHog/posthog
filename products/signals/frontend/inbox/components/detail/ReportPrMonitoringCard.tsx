import { IconTerminal, IconWarning } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { PR_MONITORING_NOTE_MAX_CHARS } from '../../logics/pullRequestsLogic'
import { SignalReportStatus } from '../../types'

export type PrMonitoringSetupStatus =
    | SignalReportStatus.IN_PROGRESS
    | SignalReportStatus.PENDING_INPUT
    | SignalReportStatus.FAILED

export interface ReportPrMonitoringCardProps {
    status: PrMonitoringSetupStatus
    guidanceQuestion: string | null
    artefactsLoading: boolean
    draftNote: string
    submitting: boolean
    disabledReason?: string
    hasResearchRun: boolean
    onChangeNote: (note: string) => void
    onSubmit: () => void
    onViewResearchRun?: () => void
}

function GuidanceDescription({
    requiresGuidance,
    artefactsLoading,
    guidanceQuestion,
}: {
    requiresGuidance: boolean
    artefactsLoading: boolean
    guidanceQuestion: string | null
}): JSX.Element {
    if (!requiresGuidance) {
        return (
            <p className="m-0 text-sm text-secondary">
                Research stopped before saving a post-merge check. Retry research, or add optional guidance on which
                event, action, or proxy metric to watch.
            </p>
        )
    }
    if (artefactsLoading && !guidanceQuestion) {
        return (
            <div className="flex flex-col gap-2" aria-label="Loading monitoring guidance question">
                <div className="h-3.5 w-11/12 rounded bg-fill-highlight-100 animate-pulse motion-reduce:animate-none" />
                <div className="h-3.5 w-3/4 rounded bg-fill-highlight-50 animate-pulse motion-reduce:animate-none" />
            </div>
        )
    }
    if (guidanceQuestion) {
        return (
            <LemonMarkdown className="text-sm text-primary leading-relaxed break-words" disableImages>
                {guidanceQuestion}
            </LemonMarkdown>
        )
    }
    return (
        <p className="m-0 text-sm text-secondary">
            Research could not pick a single metric automatically. Tell PostHog which event, action, or proxy metric to
            watch after merge.
        </p>
    )
}

function resolveSubmitDisabledReason(
    requiresGuidance: boolean,
    draftNote: string,
    disabledReason?: string
): string | undefined {
    if (disabledReason) {
        return disabledReason
    }
    if (requiresGuidance && !draftNote.trim()) {
        return 'Describe what to monitor first'
    }
    if (draftNote.length > PR_MONITORING_NOTE_MAX_CHARS) {
        return 'Shorten the note first'
    }
    return undefined
}

export function ReportPrMonitoringCard({
    status,
    guidanceQuestion,
    artefactsLoading,
    draftNote,
    submitting,
    disabledReason,
    hasResearchRun,
    onChangeNote,
    onSubmit,
    onViewResearchRun,
}: ReportPrMonitoringCardProps): JSX.Element {
    const viewRunButton =
        hasResearchRun && onViewResearchRun ? (
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconTerminal />}
                onClick={onViewResearchRun}
                // pinned: data-attr — renaming breaks Playwright selectors and autocapture
                data-attr="inbox-report-pr-monitoring-view-run"
            >
                View research run
            </LemonButton>
        ) : null

    if (status === SignalReportStatus.IN_PROGRESS) {
        return (
            <LemonCard
                hoverEffect={false}
                className="flex flex-col gap-3 bg-surface-secondary p-4 shadow-none"
                // pinned: data-attr — renaming breaks Playwright selectors and autocapture
                data-attr="inbox-report-pr-monitoring-card"
            >
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                        <Spinner className="shrink-0 text-sm" />
                        <span className="text-sm font-semibold text-primary">
                            Researching how to monitor this pull request
                        </span>
                    </div>
                    {viewRunButton}
                </div>
                <p className="m-0 text-sm text-secondary">
                    PostHog is inspecting the pull request diff and project events to choose a post-merge impact metric.
                </p>
            </LemonCard>
        )
    }

    const requiresGuidance = status === SignalReportStatus.PENDING_INPUT
    const submitDisabledReason = resolveSubmitDisabledReason(requiresGuidance, draftNote, disabledReason)
    const canSubmit = !submitting && !submitDisabledReason

    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col gap-3 bg-surface-secondary p-4 shadow-none"
            // pinned: data-attr — renaming breaks Playwright selectors and autocapture
            data-attr="inbox-report-pr-monitoring-card"
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                    {!requiresGuidance && <IconWarning className="size-4 shrink-0 text-warning" />}
                    <span className="text-sm font-semibold text-primary">
                        {requiresGuidance ? 'Guidance needed to monitor this pull request' : 'Monitoring setup failed'}
                    </span>
                </div>
                {viewRunButton}
            </div>

            <GuidanceDescription
                requiresGuidance={requiresGuidance}
                artefactsLoading={artefactsLoading}
                guidanceQuestion={guidanceQuestion}
            />

            <div className="flex flex-col gap-2">
                <LemonTextArea
                    minRows={2}
                    maxRows={5}
                    maxLength={PR_MONITORING_NOTE_MAX_CHARS}
                    value={draftNote}
                    disabled={submitting}
                    aria-label="Monitoring guidance"
                    // pinned: data-attr — renaming breaks Playwright selectors and autocapture
                    data-attr="inbox-report-pr-monitoring-note"
                    placeholder={
                        requiresGuidance
                            ? 'Tell PostHog which event, action, or proxy metric to watch after merge'
                            : 'Optional: tell PostHog which event, action, or proxy metric to watch'
                    }
                    onChange={onChangeNote}
                    onPressCmdEnter={() => {
                        if (canSubmit) {
                            onSubmit()
                        }
                    }}
                />
                <div className="flex flex-wrap items-center justify-end gap-2">
                    <LemonButton
                        size="small"
                        type="primary"
                        loading={submitting}
                        disabledReason={submitDisabledReason}
                        onClick={onSubmit}
                        // pinned: data-attr — renaming breaks Playwright selectors and autocapture
                        data-attr="inbox-report-pr-monitoring-submit"
                    >
                        {requiresGuidance ? 'Run with guidance' : 'Retry research'}
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
