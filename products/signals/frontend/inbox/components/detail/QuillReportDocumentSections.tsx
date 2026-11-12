import { ReactNode } from 'react'

import { IconCode, IconDocument } from '@posthog/icons'

import { SignalReport } from '../../types'
import { SignalReportBillingBadge } from '../badges/SignalReportBillingBadge'
import { DetailSection } from './DetailSection'

/** The report's full text and its diff. The flag-off page shows both in tabs, and the Quill page has no tabs. */
export function QuillReportDocumentSections({
    report,
    fullReport,
    generatedAt,
    showFilesTab,
    diffStat,
    diffSection,
    onToggle,
}: {
    report: SignalReport
    fullReport: ReactNode
    generatedAt: ReactNode
    diffStat: ReactNode
    showFilesTab: boolean
    diffSection: ReactNode
    onToggle: (section: string) => (collapsed: boolean) => void
}): JSX.Element {
    return (
        <>
            <DetailSection
                icon={<IconDocument />}
                title="Full report"
                afterTitle={<SignalReportBillingBadge report={report} />}
                line={{ text: generatedAt }}
                collapsible
                defaultCollapsed
                onToggleCollapsed={onToggle('full_report')}
            >
                {fullReport}
            </DetailSection>
            {showFilesTab && (
                <DetailSection
                    icon={<IconCode />}
                    title="Files changed"
                    line={{ text: diffStat }}
                    collapsible
                    defaultCollapsed
                    onToggleCollapsed={onToggle('files_changed')}
                >
                    {diffSection}
                </DetailSection>
            )}
        </>
    )
}
