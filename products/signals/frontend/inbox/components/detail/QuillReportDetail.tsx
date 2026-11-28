import {
    IconArrowLeft,
    IconChevronDown,
    IconCopy,
    IconEllipsis,
    IconHide,
    IconThumbsDown,
    IconThumbsUp,
    IconUndo,
} from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Tabs,
    TabsContent,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import type { SignalReportCheckApi } from 'products/signals/frontend/generated/api.schemas'

import { SignalReport, SignalReportArtefact, SignalReportStatus } from '../../types'
import { ReportMetricSeriesPoints } from '../../utils/reportMetrics'
import { ImplementationAgent } from './implementationAgents'
import { reportActivityEntries } from './stages/reportActivityEntries'
import { ReportExecuteStage } from './stages/ReportExecuteStage'
import { ReportMeasureStage } from './stages/ReportMeasureStage'
import { ReportSpecStage } from './stages/ReportSpecStage'
import { ReportStageActionHandlers, ReportStageActions } from './stages/ReportStageActions'
import { ReportStageActivity } from './stages/ReportStageActivity'
import { ReportStageHeader } from './stages/ReportStageHeader'
import { ReportStage } from './stages/reportStages'
import { ReportStageTabs } from './stages/ReportStageTabs'

export interface QuillReportDetailHandlers extends ReportStageActionHandlers {
    /** Hands the proposed change to the agent the reader picked. */
    onSendTo: (agent: ImplementationAgent) => void
    onCopyPrompt: () => void
    onCopyLink: () => void
    onRate: (useful: boolean) => void
    onReopen: () => void
    onNavigate: (direction: 'previous' | 'next') => void
    onComment: (comment: string) => void
}

export interface QuillReportDetailProps {
    report: SignalReport
    signals: SignalNode[]
    artefacts: SignalReportArtefact[]
    checks: SignalReportCheckApi[]
    /** The primary metric by day, through now. */
    metricPoints: ReportMetricSeriesPoints | null
    isClaimedByMe: boolean
    /** Where the report sits in the list it was opened from. Null when it was opened by link. */
    position: { index: number; total: number } | null
    stage: ReportStage
    onStageChange: (stage: ReportStage) => void
    handlers: QuillReportDetailHandlers
}

/**
 * One report as three stages: Spec (what is wrong), Execute (the work that fixes it) and Measure
 * (whether the fix held). The view takes its data and handlers as props, so the scene decides where
 * they come from.
 */
export function QuillReportDetail({
    report,
    signals,
    artefacts,
    checks,
    metricPoints,
    isClaimedByMe,
    position,
    stage,
    onStageChange,
    handlers,
}: QuillReportDetailProps): JSX.Element {
    const canReopen = report.status === SignalReportStatus.MONITORING || report.status === SignalReportStatus.CLOSED

    return (
        <div data-quill className="@container mx-auto flex w-full max-w-3xl flex-col gap-6 px-5 py-6">
            <nav className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1" aria-label="Report">
                <Button
                    variant="link-muted"
                    size="sm"
                    className="-ms-2"
                    render={<LinkPrimitive to={urls.inbox('reports')} />}
                    data-attr="inbox-report-back"
                >
                    <IconArrowLeft />
                    Inbox
                </Button>
                <div className="-me-1.5 flex items-center gap-0.5">
                    <Button
                        variant="link-muted"
                        size="sm"
                        onClick={handlers.onCopyPrompt}
                        tooltip="Copy this report as a prompt for your own AI agent"
                        data-attr="inbox-report-copy-prompt"
                    >
                        <IconCopy />
                        Copy prompt
                    </Button>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="This report is useful"
                        tooltip="This report is useful"
                        onClick={() => handlers.onRate(true)}
                        data-attr="inbox-report-rate-up"
                    >
                        <IconThumbsUp />
                    </Button>
                    <Button
                        variant="link-muted"
                        size="icon-sm"
                        aria-label="This report is not useful"
                        tooltip="This report is not useful"
                        onClick={() => handlers.onRate(false)}
                        data-attr="inbox-report-rate-down"
                    >
                        <IconThumbsDown />
                    </Button>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    variant="link-muted"
                                    size="icon-sm"
                                    aria-label="More actions"
                                    tooltip="More actions"
                                    data-attr="inbox-report-more-actions"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={handlers.onCopyLink}>
                                <IconCopy />
                                Copy link
                            </DropdownMenuItem>
                            {canReopen && (
                                <DropdownMenuItem onClick={handlers.onReopen}>
                                    <IconUndo />
                                    Reopen
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem variant="destructive" onClick={handlers.onDismiss}>
                                <IconHide />
                                Dismiss
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                    {position && (
                        <>
                            <Text size="xs" variant="muted" render={<span />} className="ps-2 pe-1 tabular-nums">
                                {`${position.index} of ${position.total}`}
                            </Text>
                            <Button
                                variant="link-muted"
                                size="icon-sm"
                                aria-label="Previous report"
                                tooltip="Previous report"
                                disabledReason={position.index <= 1 ? 'This is the first report' : null}
                                onClick={() => handlers.onNavigate('previous')}
                                data-attr="inbox-report-previous"
                            >
                                <IconChevronDown className="rotate-180" />
                            </Button>
                            <Button
                                variant="link-muted"
                                size="icon-sm"
                                aria-label="Next report"
                                tooltip="Next report"
                                disabledReason={position.index >= position.total ? 'This is the last report' : null}
                                onClick={() => handlers.onNavigate('next')}
                                data-attr="inbox-report-next"
                            >
                                <IconChevronDown />
                            </Button>
                        </>
                    )}
                </div>
            </nav>

            <ReportStageHeader report={report} isClaimedByMe={isClaimedByMe} />

            <Tabs value={stage} onValueChange={(value) => onStageChange(value as ReportStage)} className="gap-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    <ReportStageTabs report={report} />
                    <ReportStageActions report={report} handlers={handlers} />
                </div>
                <TabsContent value="spec">
                    <ReportSpecStage report={report} signals={signals} />
                </TabsContent>
                <TabsContent value="execute">
                    <ReportExecuteStage
                        report={report}
                        artefacts={artefacts}
                        isClaimedByMe={isClaimedByMe}
                        onSendTo={handlers.onSendTo}
                    />
                </TabsContent>
                <TabsContent value="measure">
                    <ReportMeasureStage report={report} checks={checks} metricPoints={metricPoints} />
                </TabsContent>
            </Tabs>

            <ReportStageActivity entries={reportActivityEntries(report, artefacts)} onComment={handlers.onComment} />
        </div>
    )
}
