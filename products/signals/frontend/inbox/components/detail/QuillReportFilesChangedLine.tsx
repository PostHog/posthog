import { ReactNode } from 'react'

import { IconCode } from '@posthog/icons'

import { DetailSection } from './DetailSection'

/** The diff of the pull request. The flag-off page shows it in a tab. */
export function QuillReportFilesChangedLine({
    diffStat,
    onToggleCollapsed,
    children,
}: {
    diffStat: ReactNode
    onToggleCollapsed: (collapsed: boolean) => void
    children: ReactNode
}): JSX.Element {
    return (
        <DetailSection
            icon={<IconCode />}
            title="Files changed"
            line={{ text: diffStat }}
            collapsible
            defaultCollapsed
            onToggleCollapsed={onToggleCollapsed}
        >
            {children}
        </DetailSection>
    )
}
