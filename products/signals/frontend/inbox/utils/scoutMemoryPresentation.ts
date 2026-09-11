import { urls } from 'scenes/urls'

import { displayConventionalCommitTitle } from './reportPresentation'

/**
 * A report id as the pipeline writes it into a note. Derived notes name the report they came from by
 * uuid, which tells a reader nothing — the note's whole value is which report it is about.
 *
 * A uuid that already sits in a link target is left alone: rewriting it would break the link the
 * note author wrote.
 */
const REPORT_ID_IN_NOTE = /(?<![/(])\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi

/** Only the leading chunk of a uuid earns space once it is clear nobody can resolve it. */
function truncateReportId(id: string): string {
    return `\`${id.slice(0, 8)}…\``
}

/**
 * The note, with every report id that resolves to a report this scout touched rewritten as a
 * markdown link carrying the report's title. Ids that resolve to nothing — an older window, a
 * deleted report — shrink to a truncated code span, because the full uuid wraps to a second line
 * and says no more than its head does.
 */
export function linkReportIdsInNote(
    content: string,
    reportsById: Map<string, { id: string; title: string | null }>
): string {
    return content.replace(REPORT_ID_IN_NOTE, (id) => {
        const report = reportsById.get(id.toLowerCase())
        if (!report) {
            return truncateReportId(id)
        }
        // Brackets in a title would close the link label early, so they go.
        const label = displayConventionalCommitTitle(report.title, 'Untitled report').replace(/[[\]]/g, '')
        return `[${label}](${urls.inboxReport('reports', report.id)})`
    })
}

/**
 * A scratchpad entry split into what to show as its title and what to show under it. Scouts write
 * these as markdown, opening with a heading, so the heading is the entry's own name for itself —
 * better than the storage key, which is a slug.
 *
 * Falls back to the key body for an entry that opens straight into prose.
 */
export function scratchpadEntryTitle(content: string | null | undefined, fallback: string): string {
    const heading = content
        ?.split('\n')
        .find((line) => line.trim().length > 0)
        ?.trim()
    if (heading?.startsWith('#')) {
        const stripped = heading.replace(/^#+\s*/, '').trim()
        if (stripped) {
            return stripped
        }
    }
    return fallback
}

/** The entry's body with its opening heading removed, so a preview doesn't restate the title. */
export function scratchpadEntryBody(content: string | null | undefined): string {
    if (!content) {
        return ''
    }
    const lines = content.split('\n')
    const firstIndex = lines.findIndex((line) => line.trim().length > 0)
    if (firstIndex >= 0 && lines[firstIndex].trim().startsWith('#')) {
        return lines
            .slice(firstIndex + 1)
            .join('\n')
            .trim()
    }
    return content.trim()
}
