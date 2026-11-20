import { useValues } from 'kea'
import { router } from 'kea-router'
import { ReactNode } from 'react'

import { Tabs, TabsContent } from '@posthog/quill'

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
import { REPORT_STAGES, ReportStage, currentReportStage } from './stages/reportStages'
import { ReportStageTabs } from './stages/ReportStageTabs'

export interface QuillReportStageSlots {
    /** The detail lines of each stage. Each line is closed until a person opens it. */
    specDetails?: ReactNode
    executeDetails?: ReactNode
    measureDetails?: ReactNode
    /** Shown inside the action card of the Execute stage. */
    executeNote?: ReactNode
}

/** The three stages of a report behind one switch. The report opens on the stage its work has reached. */
export function QuillReportStages({
    report,
    specDetails,
    executeDetails,
    measureDetails,
    executeNote,
}: { report: SignalReport } & QuillReportStageSlots): JSX.Element {
    const { reportSignals, reportArtefacts, reportChecks } = useValues(
        inboxReportDetailLogic({ reportId: report.id, report })
    )
    const metricsEnabled = useFeatureFlag('SIGNALS_REPORT_METRICS')
    const { location, searchParams, hashParams } = useValues(router)
    // The stage in view is in the URL, so a shared link opens the same stage.
    const stage: ReportStage = REPORT_STAGES.includes(searchParams.stage)
        ? searchParams.stage
        : currentReportStage(report)
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
            <div className="flex flex-wrap items-center justify-between gap-3">
                <ReportStageTabs report={report} />
                <div className="flex flex-wrap items-center gap-1">
                    {/* A report in the Measure stage waits on its checks, so it has no primary action. */}
                    {currentReportStage(report) !== 'measure' && <QuillReportPrimaryAction report={report} />}
                    <QuillReportAskButton reportId={report.id} />
                </div>
            </div>
            <QuillReportAskComposer reportId={report.id} />
            <TabsContent value="spec">
                <ReportSpecStage report={stagedReport} signals={reportSignals}>
                    {specDetails}
                </ReportSpecStage>
            </TabsContent>
            <TabsContent value="execute">
                <ReportExecuteStage report={report} artefacts={artefacts} note={executeNote}>
                    {executeDetails}
                </ReportExecuteStage>
            </TabsContent>
            <TabsContent value="measure">
                <QuillReportMeasureStage report={stagedReport} checks={reportChecks ?? []}>
                    {measureDetails}
                </QuillReportMeasureStage>
            </TabsContent>
        </Tabs>
    )
}
