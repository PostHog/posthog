// Splits a report summary into the sections the research prompt asks for: a one-sentence lead
// before any heading, then `## Problem`, `## Impact`, and `## Solution`. The structure is a prompt
// convention, not a schema: scout-authored summaries, user edits, and appended notes can all skip
// the headings, so a summary without any renders whole through `lead` and an empty `sections`.
//
// Parsed with mdast rather than a line regex for the same reason as `chartPlacement`: the renderer
// resolves `chart:` references by their offset into the raw summary, so each section carries the
// offset its body starts at and the body is a verbatim slice of the source.

import { fromMarkdown } from 'mdast-util-from-markdown'

export type ReportSummarySectionKind = 'problem' | 'impact' | 'solution' | 'other'

export interface ReportSummarySection {
    kind: ReportSummarySectionKind
    /** Heading as shown. Known kinds use the canonical label; others keep the author's text. */
    heading: string
    /** Raw markdown under the heading, trimmed. */
    body: string
    /** Offset of `body` in the full summary, so chart placements resolve against the original. */
    bodyOffset: number
}

export interface ParsedReportSummary {
    /** Markdown before the first heading, trimmed. The whole summary when there are no headings. */
    lead: string
    /** Offset of `lead` in the full summary, so chart placements resolve against the original. */
    leadOffset: number
    sections: ReportSummarySection[]
}

const SECTION_LABELS: Record<Exclude<ReportSummarySectionKind, 'other'>, string> = {
    problem: 'Problem',
    impact: 'Impact',
    solution: 'Solution',
}

// The prompt says `## Solution`; the aliases cover the phrasings models and people drift to.
const SECTION_KINDS: Record<string, Exclude<ReportSummarySectionKind, 'other'>> = {
    problem: 'problem',
    'the problem': 'problem',
    impact: 'impact',
    solution: 'solution',
    fix: 'solution',
    'the fix': 'solution',
    'proposed fix': 'solution',
    'recommended fix': 'solution',
    recommendation: 'solution',
}

function headingText(node: any): string {
    const collect = (child: any): string =>
        typeof child?.value === 'string' ? child.value : (child?.children ?? []).map(collect).join('')
    return collect(node).trim().replace(/:$/, '').trim()
}

function sectionKind(heading: string): ReportSummarySectionKind {
    return SECTION_KINDS[heading.toLowerCase()] ?? 'other'
}

/**
 * Definitions (`[id]: chart:x`) resolve anywhere in the summary, so a slice that doesn't already hold
 * one gets it appended. Appending keeps the offsets of everything before it intact.
 */
function withDefinitions(summary: string, children: any[], body: string, start: number, end: number): string {
    const missing = children
        .filter((node) => node?.type === 'definition' && node.position)
        .filter((node) => node.position.start.offset < start || node.position.start.offset >= end)
        .map((node) => summary.slice(node.position.start.offset, node.position.end.offset))
    return missing.length > 0 && body ? `${body}\n\n${missing.join('\n')}` : body
}

/** Leading whitespace trimmed with the offset moved past it, so `bodyOffset` still lands on the body. */
function trimmedSlice(summary: string, start: number, end: number): { text: string; offset: number } {
    const raw = summary.slice(start, end)
    const leading = raw.length - raw.trimStart().length
    return { text: raw.trim(), offset: start + leading }
}

export function parseReportSummary(summary: string | null | undefined): ParsedReportSummary {
    const source = typeof summary === 'string' ? summary : ''
    // `leadOffset` points the renderer past any leading whitespace: chart placements are keyed on
    // offsets into the untrimmed summary, but `lead` is trimmed for display. Zero when the lead is
    // empty — there is nothing to place a chart against.
    const leadSlice = trimmedSlice(source, 0, source.length)
    const whole: ParsedReportSummary = {
        lead: leadSlice.text,
        leadOffset: leadSlice.text ? leadSlice.offset : 0,
        sections: [],
    }
    if (!whole.lead) {
        return whole
    }

    let children: any[]
    try {
        children = fromMarkdown(source).children ?? []
    } catch {
        return whole
    }

    // A heading splits the summary into sections when it names a recognized section (Problem /
    // Impact / Solution and their aliases) or sits at or above the depth of the section already open.
    // An unrecognized, deeper heading — e.g. `### Rollout` under `## Solution` — is a subheading, so
    // it stays inside the current section's body. Headings past depth 3 never split (H4+ stay in a body).
    const headingIndexes: number[] = []
    let openDepth = Number.POSITIVE_INFINITY
    children.forEach((node, index) => {
        if (node?.type !== 'heading' || node.depth > 3 || !node.position) {
            return
        }
        if (sectionKind(headingText(node)) !== 'other' || node.depth <= openDepth) {
            headingIndexes.push(index)
            openDepth = node.depth
        }
    })
    if (headingIndexes.length === 0) {
        return whole
    }

    const leadEnd = children[headingIndexes[0]].position.start.offset
    const lead = trimmedSlice(source, 0, leadEnd)
    const sections = headingIndexes.map((headingIndex, position): ReportSummarySection => {
        const heading = headingText(children[headingIndex])
        const kind = sectionKind(heading)
        const bodyStart = children[headingIndex].position.end.offset
        const next = headingIndexes[position + 1]
        const bodyEnd = next === undefined ? source.length : children[next].position.start.offset
        const body = trimmedSlice(source, bodyStart, bodyEnd)
        return {
            kind,
            heading: kind === 'other' ? heading : SECTION_LABELS[kind],
            body: withDefinitions(source, children, body.text, bodyStart, bodyEnd),
            bodyOffset: body.offset,
        }
    })

    return {
        lead: withDefinitions(source, children, lead.text, 0, leadEnd),
        leadOffset: lead.text ? lead.offset : 0,
        sections,
    }
}
