import { useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { Skeleton } from '@posthog/quill'

import 'scenes/project-homepage/today/Today.scss'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { TodayReportLiveBody } from 'scenes/project-homepage/today/TodayReportLiveBody'
import { todayReportLogic } from 'scenes/project-homepage/today/todayReportLogic'

import { SignalReport } from '../../types'
import { ReportDetail } from '../detail/ReportDetail'
import { InboxTodayReportDetails } from './InboxTodayReportDetails'

/**
 * A report in the inbox, drawn as the Home single-page report with the inbox sections below it.
 * When the Home page data fails to load, the classic detail takes over, so the report stays usable.
 */
export function InboxTodayReportDetail({
    report,
    backUrl,
    backLabel,
}: {
    report: SignalReport
    backUrl: string
    backLabel: string
}): JSX.Element {
    const { page, reportFailed } = useValues(todayReportLogic({ reportId: report.id }))
    if (reportFailed) {
        return <ReportDetail report={report} />
    }
    return (
        <div className="Today flex-1 min-h-full">
            <div className="TodayReport Today__page">
                <nav className="TodayReportNav" aria-label="Report navigation">
                    <LinkPrimitive to={backUrl} className="TodayReportNav__back" data-attr="inbox-today-report-back">
                        <IconArrowLeft className="size-3.5" aria-hidden />
                        <span>{backLabel}</span>
                    </LinkPrimitive>
                </nav>
                {page ? (
                    <>
                        <div data-quill>
                            <TodayReportLiveBody report={report} linksToInbox={false} />
                        </div>
                        <div className="mt-10">
                            <InboxTodayReportDetails report={report} />
                        </div>
                    </>
                ) : (
                    <div className="flex flex-col gap-3" data-quill aria-busy>
                        <Skeleton className="h-3 w-48" />
                        <Skeleton className="h-6 w-4/5" />
                        <Skeleton className="h-3.5 w-full" />
                        <Skeleton className="h-3.5 w-2/3" />
                    </div>
                )}
            </div>
        </div>
    )
}
