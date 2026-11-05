import { Text } from '@posthog/quill'

import { TodayHomeHeading } from 'scenes/project-homepage/today/TodayHomeHeading'

import { MockInboxHeader } from './MockInboxHeader'
import { MockReportRow } from './MockReportRow'
import { type MockStage, reportsInStage } from './mockupData'
import { MockupPage } from './MockupPage'

const STAGES: { stage: MockStage; title: string; hint: string }[] = [
    { stage: 'review', title: 'Review', hint: 'A fix is ready. Check it and merge it.' },
    { stage: 'decide', title: 'Decide', hint: 'An agent has a proposal. Implement it or dismiss it.' },
    { stage: 'watching', title: 'Watching', hint: 'A check runs after the merge. Nothing to do yet.' },
]

export function IdeaStagesInbox(): JSX.Element {
    return (
        <MockupPage>
            <div className="flex flex-col gap-10">
                <MockInboxHeader />
                {STAGES.map(({ stage, title, hint }, index) => {
                    const reports = reportsInStage(stage)
                    return (
                        <section key={stage} className="TodayHome__list" aria-label={title}>
                            <div className="flex flex-col gap-0.5">
                                <TodayHomeHeading count={reports.length}>{title}</TodayHomeHeading>
                                <Text size="xs" variant="muted" render={<p />}>
                                    {hint}
                                </Text>
                            </div>
                            <ol className="TodayRows">
                                {reports.map((report, rowIndex) => (
                                    <MockReportRow
                                        key={report.id}
                                        report={report}
                                        defaultExpanded={index === 0 && rowIndex === 0}
                                    />
                                ))}
                            </ol>
                        </section>
                    )
                })}
            </div>
        </MockupPage>
    )
}
