import type { MCPMissingCapabilitiesItem } from '~/queries/schema/schema-general'

import { SessionDrawer } from '../sessions/SessionDrawer'

export function MissingCapabilitySessionDrawer({
    reports,
    openedReport,
    onOpen,
}: {
    reports: MCPMissingCapabilitiesItem[]
    openedReport: MCPMissingCapabilitiesItem | null
    /** null closes. */
    onOpen: (report: MCPMissingCapabilitiesItem | null) => void
}): JSX.Element | null {
    const index = openedReport ? reports.indexOf(openedReport) : -1
    if (!openedReport || index < 0) {
        return null
    }
    const previous = index > 0 ? reports[index - 1] : null
    const next = index < reports.length - 1 ? reports[index + 1] : null
    return (
        <SessionDrawer
            sessionId={openedReport.session_id || null}
            timestamp={openedReport.timestamp}
            focusedReport={openedReport.intent}
            noun="report"
            position={{ index, total: reports.length }}
            onPrevious={previous ? () => onOpen(previous) : null}
            onNext={next ? () => onOpen(next) : null}
            onClose={() => onOpen(null)}
            dataAttr="mcp-missing-capability-session-drawer"
        />
    )
}
