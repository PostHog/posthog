import { IconArrowRight } from '@posthog/icons'
import { Button, Heading, Text } from '@posthog/quill'

import { TodayHomeHeading } from 'scenes/project-homepage/today/TodayHomeHeading'
import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'

import { MockInboxHeader } from './MockInboxHeader'
import { MockNextStep } from './MockNextStep'
import { MockReportMeta } from './MockReportMeta'
import { MockTrend } from './MockTrend'
import { LEAD_REPORT, OPEN_REPORTS } from './mockupData'
import { rowFacts } from './mockupFormat'
import { MockupPage } from './MockupPage'
import { MockVerdictButtons } from './MockVerdictButtons'

export function IdeaBriefingInbox(): JSX.Element {
    const lead = LEAD_REPORT
    const rest = OPEN_REPORTS.filter((report) => report.id !== lead.id)
    const needsYou = OPEN_REPORTS.filter((report) => report.stage !== 'watching').length
    return (
        <MockupPage>
            <div className="flex flex-col gap-8">
                <MockInboxHeader />
                <Text size="sm" variant="muted" render={<p />}>
                    {`${needsYou} reports need you. 1 is urgent.`}
                </Text>
                <article className="InboxMockup__lead" aria-label="Top report">
                    <MockReportMeta report={lead} actions={<MockVerdictButtons labelled />} />
                    <Heading size="lg" render={<h2 />} className="leading-snug text-balance">
                        {lead.title}
                    </Heading>
                    <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                        {lead.abstract}
                    </Text>
                    {lead.trend && <MockTrend trend={lead.trend} />}
                    <div className="flex flex-wrap items-end justify-between gap-3">
                        <MockNextStep report={lead} />
                        <Button variant="link-muted" size="sm" className="-me-2">
                            Full report
                            <IconArrowRight />
                        </Button>
                    </div>
                </article>
                <section className="TodayHome__list" aria-label="Also for you">
                    <TodayHomeHeading count={rest.length}>Also for you</TodayHomeHeading>
                    <ol className="TodayRows">
                        {rest.map((report) => (
                            <TodayRow
                                key={report.id}
                                tone={priorityTone(report.priority)}
                                icon={reportIcon({ source_products: [report.source] })}
                                title={report.title}
                                label={report.priority}
                                facts={rowFacts(report)}
                                actions={<MockVerdictButtons />}
                                dataAttr="inbox-mockup-report"
                            />
                        ))}
                    </ol>
                </section>
            </div>
        </MockupPage>
    )
}
