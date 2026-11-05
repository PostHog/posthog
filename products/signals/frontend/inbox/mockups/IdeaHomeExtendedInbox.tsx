import { IconChevronDown } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { TodayHomeHeading } from 'scenes/project-homepage/today/TodayHomeHeading'

import { MockInboxHeader } from './MockInboxHeader'
import { MockReportRow } from './MockReportRow'
import { DONE_REPORTS, OPEN_REPORTS } from './mockupData'
import { MockupPage } from './MockupPage'

export function IdeaHomeExtendedInbox(): JSX.Element {
    return (
        <MockupPage>
            <div className="flex flex-col gap-10">
                <MockInboxHeader />
                <section className="TodayHome__list" aria-label="For you">
                    <TodayHomeHeading count={OPEN_REPORTS.length}>For you</TodayHomeHeading>
                    <ol className="TodayRows">
                        {OPEN_REPORTS.map((report, index) => (
                            <MockReportRow key={report.id} report={report} defaultExpanded={index === 0} />
                        ))}
                    </ol>
                    <div className="TodayRows__footer">
                        <Button className="TodayRows__more">
                            <IconChevronDown className="TodayRows__moreIcon" aria-hidden />
                            <span>Show more</span>
                        </Button>
                    </div>
                </section>
                <section className="TodayHome__list" aria-label="Done this week">
                    <TodayHomeHeading count={DONE_REPORTS.length}>Done this week</TodayHomeHeading>
                    <ol className="TodayRows">
                        {DONE_REPORTS.map((report) => (
                            <MockReportRow key={report.id} report={report} />
                        ))}
                    </ol>
                </section>
            </div>
        </MockupPage>
    )
}
