import './QuillReportDetail.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import 'scenes/project-homepage/today/Today.scss'
import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TodayReportFeedback } from 'scenes/project-homepage/today/TodayReportFeedback'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportTitle } from 'scenes/project-homepage/today/TodayReportTitle'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { reportNotesFromArtefacts } from '../../utils/reportNotes'
import { QuillReportFactLine } from './QuillReportFactLine'
import { QuillReportNav } from './QuillReportNav'
import { QuillReportNavActions } from './QuillReportNavActions'
import { QuillReportStageSlots, QuillReportStages } from './QuillReportStages'
import { ReportDetailAction } from './ReportDetailActions'
import { ReportNotesSection } from './ReportNotesSection'
import { reportActivityEntries } from './stages/reportActivityEntries'
import { ReportStageActivity } from './stages/ReportStageActivity'
import { useQuillReportClaim } from './useQuillReportClaim'

/**
 * One report as three stages: Spec (what is wrong), Execute (the work that fixes it) and Measure
 * (whether the fix held). The facts and the activity stay in view on every stage.
 */
export function QuillReportDetail({
    report,
    backUrl,
    backLabel,
    actions,
    notesEnabled,
    banner,
    activityDetails,
    ...stageSlots
}: {
    report: SignalReport
    backUrl: string
    backLabel: string
    actions: ReportDetailAction[]
    notesEnabled: boolean
    banner?: ReactNode
    /** The detail lines of the work log. */
    activityDetails?: ReactNode
} & QuillReportStageSlots): JSX.Element {
    const detailLogic = inboxReportDetailLogic({ reportId: report.id, report })
    const { report: currentReport, reportArtefacts, prioritySaving } = useValues(detailLogic)
    const { updatePriority } = useActions(detailLogic)
    const { reportChanged } = useActions(todayReportLogic({ reportId: report.id }))
    const liveReport = currentReport ?? report
    const claim = useQuillReportClaim(liveReport)
    const artefacts = reportArtefacts ?? []
    // The notes list shows the notes that people left, so the work log does not repeat them.
    const noteIds = new Set(notesEnabled ? reportNotesFromArtefacts(artefacts).map((note) => note.id) : [])
    const activity = reportActivityEntries(liveReport, artefacts).filter((entry) => !noteIds.has(entry.id))

    useEffect(() => {
        reportChanged(liveReport)
    }, [liveReport, reportChanged])

    return (
        <div className="Today min-h-full flex-1">
            <div className="TodayReport Today__page @container" data-quill>
                <QuillReportNav
                    reportId={report.id}
                    backUrl={backUrl}
                    backLabel={backLabel}
                    actions={<QuillReportNavActions report={liveReport} />}
                />
                <QuillSurfaceContext.Provider value>
                    <article className="TodayReportArticle flex flex-col gap-6">
                        <header className="flex flex-col gap-3">
                            <QuillReportFactLine
                                report={liveReport}
                                claim={claim}
                                actions={actions}
                                prioritySaving={prioritySaving}
                                onPriorityChange={(priority) => {
                                    captureInboxReportAction({
                                        report,
                                        actionType: 'change_priority',
                                        surface: 'detail_pane',
                                        extra: { new_priority: priority },
                                    })
                                    updatePriority(priority)
                                }}
                            />
                            <TodayReportTitle report={liveReport} />
                            {claim.dialog}
                        </header>
                        {banner}
                        <QuillReportStages report={liveReport} {...stageSlots} />
                        <ReportStageActivity
                            entries={activity}
                            notes={notesEnabled ? <ReportNotesSection report={report} /> : null}
                        >
                            {activityDetails}
                        </ReportStageActivity>
                        <footer className="border-t border-(--today-line) pt-4">
                            <TodayReportFeedback report={liveReport} />
                        </footer>
                    </article>
                </QuillSurfaceContext.Provider>
            </div>
        </div>
    )
}
