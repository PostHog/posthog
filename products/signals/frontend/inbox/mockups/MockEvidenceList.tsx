import { Button, Text } from '@posthog/quill'

import { TodayIcon } from 'scenes/project-homepage/today/TodayIcon'
import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'
import { sourceStyle } from 'scenes/project-homepage/today/todaySignalReports'

import type { MockReport } from './mockupData'

export function MockEvidenceList({
    report,
    numbered = false,
}: {
    report: MockReport
    numbered?: boolean
}): JSX.Element {
    return (
        <section className="flex flex-col gap-1" aria-label="Evidence">
            <div className="flex items-baseline justify-between gap-3">
                <TodaySectionTitle>Evidence</TodaySectionTitle>
                {report.evidenceCount > report.evidence.length && (
                    <Button variant="link-muted" size="sm" className="-me-2">
                        {`See all ${report.evidenceCount}`}
                    </Button>
                )}
            </div>
            {report.evidence.length === 0 ? (
                <Text size="sm" variant="muted" render={<p />}>
                    No signals are attached to this report yet.
                </Text>
            ) : (
                <ol className="InboxMockup__evidence">
                    {report.evidence.map((item, index) => (
                        <li
                            key={item.id}
                            id={numbered ? `${report.id}-evidence-${index + 1}` : undefined}
                            className="InboxMockup__evidenceRow"
                        >
                            {numbered && <span className="InboxMockup__footnoteNumber">{index + 1}</span>}
                            <div className="min-w-0">
                                <p className="InboxMockup__evidenceHeadline">{item.headline}</p>
                                <p className="InboxMockup__muted">{item.meta}</p>
                            </div>
                            <span className="InboxMockup__evidenceSource" title={sourceStyle(item.source).label}>
                                <TodayIcon icon={sourceStyle(item.source).icon} />
                                <span>{item.date}</span>
                            </span>
                        </li>
                    ))}
                </ol>
            )}
        </section>
    )
}
