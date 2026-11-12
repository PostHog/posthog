import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayReportAbstract } from 'scenes/project-homepage/today/TodayReportAbstract'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'
import { TodayReportNextStep } from 'scenes/project-homepage/today/TodayReportNextStep'
import { TodayReportProposal } from 'scenes/project-homepage/today/TodayReportProposal'
import { TodayReportTitle } from 'scenes/project-homepage/today/TodayReportTitle'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { QuillReportFactLine } from './QuillReportFactLine'
import { ReportDetailAction } from './ReportDetailActions'
import { ReportNotesSection } from './ReportNotesSection'

export function QuillReportDetail({
    report,
    backUrl,
    backLabel,
    actions,
    notesEnabled,
    fallback,
    children,
}: {
    report: SignalReport
    backUrl: string
    backLabel: string
    actions: ReportDetailAction[]
    notesEnabled: boolean
    /** Shown when the Home report data does not load, so the report stays readable. */
    fallback: JSX.Element
    children: ReactNode
}): JSX.Element {
    const {
        report: currentReport,
        reportClaimant,
        isClaimedByMe,
        reportTaskToOpen,
        implementationSlotClaim,
    } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const homeLogic = todayReportLogic({ reportId: report.id })
    const { page, reportFailed } = useValues(homeLogic)
    const { reportChanged } = useActions(homeLogic)
    const liveReport = currentReport ?? report

    useEffect(() => {
        reportChanged(liveReport)
    }, [liveReport, reportChanged])

    if (reportFailed) {
        return fallback
    }

    return (
        <div className="Today min-h-full flex-1">
            <div className="TodayReport Today__page">
                <nav className="TodayReportNav" aria-label="Report navigation">
                    <LinkPrimitive to={backUrl} className="TodayReportNav__back" data-attr="inbox-report-back">
                        <IconArrowLeft className="size-3.5" />
                        <span>{backLabel}</span>
                    </LinkPrimitive>
                </nav>
                <article className="TodayReportArticle flex flex-col gap-10" data-quill>
                    <div className="flex flex-col gap-5">
                        <header className="flex flex-col gap-3">
                            <QuillReportFactLine
                                report={liveReport}
                                claimant={reportClaimant}
                                isClaimedByMe={isClaimedByMe}
                                actions={actions}
                            />
                            <TodayReportTitle report={liveReport} />
                        </header>
                        {page && <TodayReportAbstract report={liveReport} />}
                        {notesEnabled && <ReportNotesSection report={report} />}
                    </div>
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
                </article>
                <div className="mt-10">{children}</div>
            </div>
        </div>
    )
}
