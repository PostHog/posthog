import './QuillReportDetail.scss'

import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { Skeleton } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { QuillSurfaceContext } from 'lib/components/QuillSurface/quillSurfaceContext'
import { TodayReportAbstract } from 'scenes/project-homepage/today/TodayReportAbstract'
import { TodayReportFeedback } from 'scenes/project-homepage/today/TodayReportFeedback'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportNextStep } from 'scenes/project-homepage/today/TodayReportNextStep'
import { TodayReportProposal } from 'scenes/project-homepage/today/TodayReportProposal'
import { TodayReportTitle } from 'scenes/project-homepage/today/TodayReportTitle'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { captureInboxReportAction } from '../../inboxAnalytics'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillReportEvidence } from './QuillReportEvidence'
import { QuillReportFactLine } from './QuillReportFactLine'
import { QuillReportNav } from './QuillReportNav'
import { ReportDetailAction } from './ReportDetailActions'
import { ReportNotesSection } from './ReportNotesSection'
import { useQuillReportClaim } from './useQuillReportClaim'

export function QuillReportDetail({
    report,
    backUrl,
    backLabel,
    actions,
    notesEnabled,
    banner,
    fallback,
    children,
}: {
    report: SignalReport
    backUrl: string
    backLabel: string
    actions: ReportDetailAction[]
    notesEnabled: boolean
    banner?: ReactNode
    /** Shown when the Home report data does not load, so the report stays readable. */
    fallback: JSX.Element
    children: ReactNode
}): JSX.Element {
    const detailLogic = inboxReportDetailLogic({ reportId: report.id, report })
    const { report: currentReport, reportTaskToOpen, implementationSlotClaim, prioritySaving } = useValues(detailLogic)
    const { updatePriority } = useActions(detailLogic)
    const homeLogic = todayReportLogic({ reportId: report.id })
    const { page, reportFailed } = useValues(homeLogic)
    const { reportChanged } = useActions(homeLogic)
    const liveReport = currentReport ?? report
    const claim = useQuillReportClaim(liveReport)

    useEffect(() => {
        reportChanged(liveReport)
    }, [liveReport, reportChanged])

    if (reportFailed) {
        return fallback
    }

    return (
        <div className="Today min-h-full flex-1">
            <div className="TodayReport Today__page" data-quill>
                <QuillReportNav reportId={report.id} backUrl={backUrl} backLabel={backLabel} />
                <article className="TodayReportArticle flex flex-col gap-10">
                    <div className="flex flex-col gap-5">
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
                        </header>
                        {page && <TodayReportAbstract report={liveReport} />}
                        {notesEnabled && <ReportNotesSection report={report} />}
                        {claim.dialog}
                    </div>
                    {banner}
                    {page ? (
                        <section className="flex flex-col gap-4 empty:hidden" aria-label="Proposal">
                            <TodayReportProposal reportId={report.id} />
                            <TodayReportNextStep
                                report={liveReport}
                                reportTaskToOpen={reportTaskToOpen}
                                slotClaim={implementationSlotClaim}
                                surface="detail_pane"
                            />
                        </section>
                    ) : (
                        <div className="flex flex-col gap-2" aria-busy>
                            <Skeleton className="h-4 w-20" />
                            <Skeleton className="h-3.5 w-full" />
                            <Skeleton className="h-3.5 w-1/2" />
                            <Skeleton className="mt-2 h-8 w-32" />
                        </div>
                    )}
                    {page && <QuillReportEvidence reportId={report.id} />}
                    <section className="flex flex-col gap-1.5" aria-label="Details">
                        <TodaySectionTitle>Details</TodaySectionTitle>
                        <div className="-mx-2 flex flex-col">
                            <QuillSurfaceContext.Provider value>{children}</QuillSurfaceContext.Provider>
                        </div>
                    </section>
                    <footer className="border-t border-(--today-line) pt-4">
                        <TodayReportFeedback report={liveReport} />
                    </footer>
                </article>
            </div>
        </div>
    )
}
