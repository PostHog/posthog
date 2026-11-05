import { useValues } from 'kea'

import { IconSearch } from '@posthog/icons'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { FEATURE_FLAGS } from 'lib/constants'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { QuillSignalCard } from '../../QuillSignalCard'
import { SignalReport } from '../../types'
import { QuillDetailSection } from '../detail/QuillDetailSection'
import { QuillPrChecksSection } from '../detail/QuillPrChecksSection'
import { QuillPrCommentsSection } from '../detail/QuillPrCommentsSection'
import { QuillReportActivitySection } from '../detail/QuillReportActivitySection'
import { QuillReportChecksSection } from '../detail/QuillReportChecksSection'
import { QuillReportSourceSuggestion } from '../detail/QuillReportSourceSuggestion'
import { QuillReportTasksSection } from '../detail/QuillReportTasksSection'
import { QuillSuggestedReviewersSection } from '../detail/QuillSuggestedReviewersSection'
import { QuillReportSpendSection } from '../spend/QuillReportSpendSection'

/**
 * The inbox sections that the Home report page leaves out, under one "Details" heading. Each section
 * hides itself when it has nothing to show.
 */
export function InboxTodayReportDetails({ report }: { report: SignalReport }): JSX.Element {
    const { reportSignals } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    return (
        <section className="Today__page flex flex-col gap-6" aria-label="Details" data-quill>
            <TodaySectionTitle>Details</TodaySectionTitle>
            {!!reportSignals?.length && (
                <QuillDetailSection icon={<IconSearch />} title="All evidence" collapsible defaultCollapsed>
                    <div className="flex flex-col gap-3">
                        {reportSignals.map((signal) => (
                            <QuillSignalCard key={signal.signal_id} signal={signal} />
                        ))}
                        {report.source_suggestion && (
                            <QuillReportSourceSuggestion report={report} suggestion={report.source_suggestion} />
                        )}
                    </div>
                </QuillDetailSection>
            )}
            <QuillPrChecksSection report={report} />
            <QuillPrCommentsSection report={report} />
            <QuillSuggestedReviewersSection report={report} />
            <QuillReportTasksSection report={report} />
            <QuillReportChecksSection report={report} />
            <QuillReportActivitySection report={report} />
            <FlaggedFeature flag={FEATURE_FLAGS.SELF_DRIVING_USAGE_DISPLAY}>
                <QuillReportSpendSection reportId={report.id} />
            </FlaggedFeature>
        </section>
    )
}
