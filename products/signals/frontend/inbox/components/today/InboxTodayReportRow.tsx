import { memo, useState } from 'react'

import 'scenes/project-homepage/today/Today.scss'
import { dayjs } from 'lib/dayjs'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { reportPreview } from 'scenes/project-homepage/today/todayReportPreviews'
import { TodayReportRowDetail } from 'scenes/project-homepage/today/TodayReportRowDetail'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { pullRequestFact, rowFacts } from 'scenes/project-homepage/today/todayRowFacts'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'
import { reportTitle } from 'scenes/project-homepage/today/todaySignalReports'

import { InboxReportSectionKey, SignalReport, SignalReportStatus } from '../../types'
import { inboxReportDetailUrl } from '../../utils/inboxReportUrls'
import { InboxTodayVerdictButtons } from './InboxTodayVerdictButtons'

/** A report in the inbox list, drawn as a "For you" row from the Home page. Memoized like the card row. */
export const InboxTodayReportRow = memo(function InboxTodayReportRow({
    report,
    sectionKey,
}: {
    report: SignalReport
    sectionKey: InboxReportSectionKey
}): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const preview = reportPreview(report)
    const to = inboxReportDetailUrl(report.id)
    const done = report.status === SignalReportStatus.RESOLVED || report.status === SignalReportStatus.SUPPRESSED
    return (
        <TodayRow
            tone={priorityTone(report.priority)}
            icon={reportIcon(report)}
            title={reportTitle(report)}
            label={report.priority ?? undefined}
            facts={rowFacts([
                pullRequestFact(
                    report.implementation_pr_merged
                        ? 'merged'
                        : (report.implementation_pr_state ?? (report.implementation_pr_url ? 'open' : null))
                ),
                `Updated ${dayjs(report.updated_at).fromNow()}`,
            ])}
            to={to}
            expansion={
                preview
                    ? {
                          expanded,
                          onToggle: () => setExpanded((open) => !open),
                          detail: (
                              <TodayReportRowDetail
                                  preview={preview}
                                  to={to}
                                  onOpen={() => {}}
                                  actions={
                                      done ? null : (
                                          <InboxTodayVerdictButtons report={report} sectionKey={sectionKey} labelled />
                                      )
                                  }
                                  dataAttr="inbox-today-row"
                              />
                          ),
                      }
                    : undefined
            }
            actions={<InboxTodayVerdictButtons report={report} sectionKey={sectionKey} />}
            done={done}
            dataAttr="inbox-today-row"
        />
    )
})
