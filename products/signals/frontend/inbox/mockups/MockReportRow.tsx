import { useState } from 'react'

import { IconArrowRight, IconArrowUpRight, IconPullRequest } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { priorityTone } from 'scenes/project-homepage/today/todayPriority'
import { TodayRow } from 'scenes/project-homepage/today/TodayRow'
import { reportIcon } from 'scenes/project-homepage/today/todayRowIcons'

import type { MockReport } from './mockupData'
import { rowFacts } from './mockupFormat'
import { MockVerdictButtons } from './MockVerdictButtons'

export function MockReportRow({
    report,
    defaultExpanded = false,
}: {
    report: MockReport
    defaultExpanded?: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(defaultExpanded)
    const done = report.stage === 'done'
    return (
        <TodayRow
            tone={priorityTone(report.priority)}
            icon={reportIcon({ source_products: [report.source] })}
            title={report.title}
            label={report.priority}
            facts={rowFacts(report)}
            expansion={{
                expanded,
                onToggle: () => setExpanded((open) => !open),
                detail: (
                    <div className="TodayRow__detailBody">
                        <p className="TodayRow__detailLead">{report.abstract}</p>
                        <div className="TodayRow__detailFooter">
                            <p className="TodayRow__detailFacts">
                                <span>{report.sources}</span>
                                {report.pullRequest && (
                                    <>
                                        {' · '}
                                        <span className="TodayRow__detailPr">
                                            <IconPullRequest className="size-3.5" aria-hidden />
                                            <span>{`Pull request #${report.pullRequest.number}, ready for review`}</span>
                                            <IconArrowUpRight className="size-3" aria-hidden />
                                        </span>
                                    </>
                                )}
                            </p>
                            <div className="TodayRow__detailActions">
                                {!done && <MockVerdictButtons labelled />}
                                <Button variant="outline" size="sm">
                                    Open report
                                    <IconArrowRight />
                                </Button>
                            </div>
                        </div>
                    </div>
                ),
            }}
            actions={<MockVerdictButtons />}
            done={done}
            dataAttr="inbox-mockup-report"
        />
    )
}
