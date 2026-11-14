import { ReactNode } from 'react'

import { IconDocument } from '@posthog/icons'

import { SignalReport } from '../../types'
import { SignalReportBillingBadge } from '../badges/SignalReportBillingBadge'
import { DetailSection } from './DetailSection'

/** The report's full text with its charts and plan. The Spec stage shows the problem and the impact from it. */
export function QuillReportFullReportLine({
    report,
    generatedAt,
    onToggleCollapsed,
    children,
}: {
    report: SignalReport
    generatedAt: ReactNode
    onToggleCollapsed: (collapsed: boolean) => void
    children: ReactNode
}): JSX.Element {
    return (
        <DetailSection
            icon={<IconDocument />}
            title="Full report"
            afterTitle={<SignalReportBillingBadge report={report} />}
            line={{ text: generatedAt }}
            collapsible
            defaultCollapsed
            onToggleCollapsed={onToggleCollapsed}
        >
            {children}
        </DetailSection>
    )
}
