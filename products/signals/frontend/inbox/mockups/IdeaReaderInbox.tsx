import { useState } from 'react'

import { Kbd, Text } from '@posthog/quill'

import { TodayHomeHeading } from 'scenes/project-homepage/today/TodayHomeHeading'

import { MockInboxHeader } from './MockInboxHeader'
import { MockReaderRow } from './MockReaderRow'
import { MockSinglePageReport } from './MockSinglePageReport'
import { OPEN_REPORTS } from './mockupData'
import { MockupPage } from './MockupPage'

export function IdeaReaderInbox(): JSX.Element {
    const [selectedId, setSelectedId] = useState(OPEN_REPORTS[0].id)
    const selected = OPEN_REPORTS.find((report) => report.id === selectedId) ?? OPEN_REPORTS[0]
    return (
        <MockupPage width="wide">
            <div className="flex flex-col gap-8">
                <MockInboxHeader />
                <div className="InboxMockup__reader">
                    <section className="InboxMockup__readerList TodayHome__list" aria-label="For you">
                        <div className="TodayHome__headingRow">
                            <TodayHomeHeading count={OPEN_REPORTS.length}>For you</TodayHomeHeading>
                            <Text size="xs" variant="muted" render={<span />} className="flex items-center gap-1">
                                <Kbd>J</Kbd>
                                <Kbd>K</Kbd>
                                to move
                            </Text>
                        </div>
                        <ol className="TodayRows">
                            {OPEN_REPORTS.map((report) => (
                                <MockReaderRow
                                    key={report.id}
                                    report={report}
                                    selected={report.id === selected.id}
                                    onSelect={() => setSelectedId(report.id)}
                                />
                            ))}
                        </ol>
                    </section>
                    <div className="InboxMockup__readerPane">
                        <MockSinglePageReport key={selected.id} report={selected} />
                    </div>
                </div>
            </div>
        </MockupPage>
    )
}
