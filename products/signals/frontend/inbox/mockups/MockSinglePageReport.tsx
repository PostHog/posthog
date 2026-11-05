import type { ReactNode } from 'react'

import { Heading, Text } from '@posthog/quill'

import { TodaySectionTitle } from 'scenes/project-homepage/today/TodaySectionTitle'

import { MockEvidenceList } from './MockEvidenceList'
import { MockFeedback } from './MockFeedback'
import { MockNextStep } from './MockNextStep'
import { MockReportMeta } from './MockReportMeta'
import type { MockReport } from './mockupData'
import { MockVerdictButtons } from './MockVerdictButtons'

/** The Home report page, as a static copy. `children` render between the evidence and the feedback. */
export function MockSinglePageReport({ report, children }: { report: MockReport; children?: ReactNode }): JSX.Element {
    return (
        <article className="TodayReportArticle flex flex-col gap-10">
            <header className="flex flex-col gap-3">
                <MockReportMeta report={report} actions={<MockVerdictButtons labelled />} />
                <div className="flex flex-col gap-2">
                    <Heading size="xl" render={<h1 />} className="leading-snug text-balance">
                        {report.title}
                    </Heading>
                    <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                        {report.abstract}
                    </Text>
                </div>
            </header>
            <section className="flex flex-col gap-4" aria-label="Proposal">
                <div className="flex flex-col gap-2">
                    <TodaySectionTitle>Proposal</TodaySectionTitle>
                    <Text size="sm" render={<p />} className="leading-relaxed text-pretty">
                        {report.proposal}
                    </Text>
                </div>
                <MockNextStep report={report} />
            </section>
            <MockEvidenceList report={report} />
            {children}
            <MockFeedback />
        </article>
    )
}
