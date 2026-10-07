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
 * A report title as a markdown link label. The title is untrusted: an agent writes it from ticket
 * and issue text. The characters that escape the label are removed rather than escaped, because a
 * derived note wraps the report id in a code span, and a backslash escape inside a code span
 * renders as a literal backslash. `[` and `]` close the label, a backtick closes that code span,
 * and `<url>` renders as a link inside the link, carrying a target the title chose. Whitespace
 * collapses because a blank line ends the paragraph the link sits in. A bare url needs nothing:
 * inside a link label GFM leaves it as text.
 */
function reportLinkLabel(title: string | null, fallback: string): string {
    const label = displayConventionalCommitTitle(title, fallback)
        .replace(/[[\]`<>]/g, '')
        .replace(/\s+/g, ' ')
        .trim()
    // A title of nothing but stripped characters would render as an invisible empty link.
    return label || fallback
}

/**
 * The note, with every report id that resolves to a report this scout touched rewritten as a
 * markdown link carrying the report's title. Ids that resolve to nothing — an older window, a
 * deleted report — shrink to a truncated code span, because the full uuid wraps to a second line
 * and says no more than its head does.
 *
 * Pass `truncateUnmatched: false` for a note a person typed. Only the pipeline guarantees that
 * every uuid it writes is a report id. In typed prose a uuid can name a session, a trace, or an
 * error issue, and shortening one would corrupt a value the reader cannot recover from this page.
 */
export function linkReportIdsInNote(
    content: string,
    reportsById: Map<string, { id: string; title: string | null }>,
    { truncateUnmatched = true }: { truncateUnmatched?: boolean } = {}
): string {
    return content.replace(REPORT_ID_IN_NOTE, (id) => {
        const report = reportsById.get(id.toLowerCase())
        if (!report) {
            return truncateUnmatched ? truncateReportId(id) : id
        }
        return `[${reportLinkLabel(report.title, 'Untitled report')}](${urls.inboxReport('reports', report.id)})`
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
