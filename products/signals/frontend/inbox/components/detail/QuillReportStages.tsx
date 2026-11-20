import { useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { Tabs, TabsContent, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillReportAskButton } from './QuillReportAskButton'
import { QuillReportAskComposer } from './QuillReportAskComposer'
import { QuillReportMeasureStage } from './QuillReportMeasureStage'
import { QuillReportPrimaryAction } from './QuillReportPrimaryAction'
import { ReportExecuteStage } from './stages/ReportExecuteStage'
import { ReportSpecStage } from './stages/ReportSpecStage'
import { REPORT_STAGE_QUESTION, ReportStage, availableReportStages, currentReportStage } from './stages/reportStages'
import { ReportStageTabs } from './stages/ReportStageTabs'

export interface QuillReportStageSlots {
    /** The detail lines of each stage. Each line is closed until a person opens it. */
    specDetails?: ReactNode
    executeDetails?: ReactNode
    measureDetails?: ReactNode
    /** Shown inside the action card of the Execute stage. */
    executeNote?: ReactNode
}

/** The stages that apply to a report, behind one switch. The report opens on the stage its work has reached. */
export function QuillReportStages({
    report,
    specDetails,
    executeDetails,
    measureDetails,
    executeNote,
}: { report: SignalReport } & QuillReportStageSlots): JSX.Element {
    const { reportSignals, reportArtefacts, reportChecks, selectedPullRequest } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const metricsEnabled = useFeatureFlag('SIGNALS_REPORT_METRICS')
    const { location, searchParams, hashParams } = useValues(router)
    // The stage in view is in the URL, so a shared link opens the same stage.
    const stages = availableReportStages(report)
    const stage: ReportStage = stages.includes(searchParams.stage) ? searchParams.stage : currentReportStage(report)
    const stagedReport = metricsEnabled ? report : { ...report, metrics: undefined }
    const artefacts = reportArtefacts ?? []

    return (
        <Tabs
            value={stage}
            onValueChange={(value) => {
                router.actions.replace(location.pathname, { ...searchParams, stage: value }, hashParams)
                captureInboxReportAction({
                    report,
                    actionType: 'expand_section',
                    surface: 'detail_pane',
                    extra: { section: `stage_${value}` },
                })
            }}
            className="gap-6"
        >
            <div className="flex flex-col gap-2">
                <div className="flex flex-wrap items-center justify-between gap-3">
                    {stages.length > 1 && <ReportStageTabs report={report} stages={stages} />}
                    <div className="flex flex-wrap items-center gap-1">
                        {/* A report in the Measure stage waits on its checks, so it has no primary action. */}
                        {currentReportStage(report) !== 'measure' && <QuillReportPrimaryAction report={report} />}
                        <QuillReportAskButton reportId={report.id} />
                    </div>
                </div>
                <Text size="sm" variant="muted" render={<p className="m-0" />} data-attr="inbox-report-stage-question">
                    {REPORT_STAGE_QUESTION[stage]}
                </Text>
            </div>
            <QuillReportAskComposer reportId={report.id} />
            <TabsContent value="spec">
                <ReportSpecStage report={stagedReport} signals={reportSignals}>
                    {specDetails}
                </ReportSpecStage>
            </TabsContent>
            {stages.includes('execute') && (
                <TabsContent value="execute">
                    <ReportExecuteStage
                        report={report}
                        artefacts={artefacts}
                        selectedPullRequest={selectedPullRequest}
                        note={executeNote}
                    >
                        {executeDetails}
                    </ReportExecuteStage>
                </TabsContent>
            )}
            {stages.includes('measure') && (
                <TabsContent value="measure">
                    <QuillReportMeasureStage report={stagedReport} checks={reportChecks ?? []}>
                        {measureDetails}
                    </QuillReportMeasureStage>
                </TabsContent>
            )}
        </Tabs>
    )
}
