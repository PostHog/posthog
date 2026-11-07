import { useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalCard } from '../../SignalCard'
import { SignalReport } from '../../types'
import { DetailSection } from '../detail/DetailSection'
import { PrChecksSection } from '../detail/PrChecksSection'
import { PrCommentsSection } from '../detail/PrCommentsSection'
import { ReportActivitySection } from '../detail/ReportActivitySection'
import { ReportChecksSection } from '../detail/ReportChecksSection'
import { ReportTasksSection } from '../detail/ReportTasksSection'
import { SuggestedReviewersSection } from '../detail/SuggestedReviewersSection'
import { ReportSpendSection } from '../spend/ReportSpendSection'

/**
 * The inbox sections that the Home report page leaves out, under one "Details" heading. Each section
 * hides itself when it has nothing to show.
 */
export function InboxTodayReportDetails({ report }: { report: SignalReport }): JSX.Element {
    const { reportSignals } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    return (
        <section className="flex flex-col gap-6" aria-label="Details">
            {/* The sections below are Lemon. Inside a quill root, the quill bridge rebinds Lemon colors. */}
            <div data-quill>
                <TodaySectionTitle>Details</TodaySectionTitle>
            </div>
            {!!reportSignals?.length && (
                <DetailSection icon={<IconSearch />} title="All evidence" collapsible defaultCollapsed>
                    <div className="flex flex-col gap-3">
                        {reportSignals.map((signal) => (
                            <SignalCard key={signal.signal_id} signal={signal} />
                        ))}
                    </div>
                </DetailSection>
            )}
            <PrChecksSection report={report} />
            <PrCommentsSection report={report} />
            <SuggestedReviewersSection report={report} />
            <ReportTasksSection report={report} />
            <ReportChecksSection report={report} />
            <ReportActivitySection report={report} />
            <FlaggedFeature flag={FEATURE_FLAGS.SELF_DRIVING_USAGE_DISPLAY}>
                <ReportSpendSection reportId={report.id} />
            </FlaggedFeature>
        </section>
    )
}
