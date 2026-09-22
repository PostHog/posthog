import { parseReportSummary } from './reportSummary'

describe('parseReportSummary', () => {
    const PROMPT_SHAPED =
        'Users on the key form hit a dead button.\n\n' +
        '## Problem\n\nThe click handler returns early.\n\n' +
        '## Impact\n\n**1,410 users** in 28 hours.\n\n[Dead clicks](chart:dead-clicks)\n\n' +
        '## Solution\n\nSet the errors before the return.'

    it('splits the lead and the prompt sections, keeping each body offset into the source', () => {
        const parsed = parseReportSummary(PROMPT_SHAPED)

        expect(parsed.lead).toEqual('Users on the key form hit a dead button.')
        expect(parsed.sections.map((section) => [section.kind, section.heading, section.body])).toEqual([
            ['problem', 'Problem', 'The click handler returns early.'],
            ['impact', 'Impact', '**1,410 users** in 28 hours.\n\n[Dead clicks](chart:dead-clicks)'],
            ['solution', 'Solution', 'Set the errors before the return.'],
        ])
        for (const section of parsed.sections) {
            expect(PROMPT_SHAPED.slice(section.bodyOffset, section.bodyOffset + section.body.length)).toEqual(
                section.body
            )
        }
    })

    it.each([
        ['## Fix', 'solution', 'Solution'],
        ['## Recommended fix:', 'solution', 'Solution'],
        ['### The problem', 'problem', 'Problem'],
        ['## Next steps', 'other', 'Next steps'],
    ])('maps the heading %s to the %s section', (heading, kind, label) => {
        const [section] = parseReportSummary(`Lead.\n\n${heading}\n\nBody.`).sections

        expect(section).toMatchObject({ kind, heading: label, body: 'Body.' })
    })

    it('returns the whole summary as the lead when there are no headings', () => {
        // Scout-authored and hand-edited summaries do not promise the prompt's headings.
        const summary = 'Signups fell 40%.\n\nRecommend: roll back the flag.'

        expect(parseReportSummary(summary)).toEqual({ lead: summary, leadOffset: 0, sections: [] })
    })

    it('offsets the lead past leading whitespace so an inline chart still resolves', () => {
        // A pipeline-written summary can open with a newline. The lead is trimmed for display, but its
        // offset must point past that whitespace, or a chart placement (keyed on the untrimmed
        // summary) misses and the chart renders nowhere.
        const noHeadings = parseReportSummary('\n\nSignups fell. [Chart][c]\n\n[c]: chart:signups')
        expect(noHeadings.leadOffset).toBe(2)
        expect(noHeadings.lead).toEqual('Signups fell. [Chart][c]\n\n[c]: chart:signups')

        const withSection = parseReportSummary('  Lead line.\n\n## Impact\n\nBody.')
        expect(withSection.leadOffset).toBe(2)
        expect(withSection.lead).toEqual('Lead line.')
    })

    it.each([
        // H4 is past the section-heading cap, so it never opens a section.
        ['## Problem', '#### Detail\n\nMore.'],
        // An H3 nested under an H2 section is a subheading, not a peer section. Splitting it out would
        // also push the Create PR action (rendered at the end of the solution section) above it.
        ['## Solution', '### Rollout\n\nShip behind a flag.'],
    ])('keeps a deeper heading inside the %s section body', (sectionHeading, deeperBlock) => {
        const sections = parseReportSummary(`Lead.\n\n${sectionHeading}\n\n${deeperBlock}`).sections

        expect(sections).toHaveLength(1)
        expect(sections[0].body).toEqual(deeperBlock)
    })

    it('keeps recognized sections that follow a shallower heading', () => {
        // A stray shallower heading (e.g. a document title) must not swallow the recognized sections
        // below it: Problem and Solution are named sections, so they still split into their own.
        const parsed = parseReportSummary('Lead.\n\n# Report\n\n## Problem\n\nA.\n\n## Solution\n\nB.')

        expect(parsed.sections.map((section) => section.kind)).toEqual(['other', 'problem', 'solution'])
    })

    it('appends reference definitions to every slice so chart links still resolve', () => {
        const summary = 'Lead [Daily][d].\n\n## Impact\n\n[Daily][d]\n\n[d]: chart:daily'
        const parsed = parseReportSummary(summary)

        expect(parsed.lead).toEqual('Lead [Daily][d].\n\n[d]: chart:daily')
        expect(parsed.sections[0].body).toEqual('[Daily][d]\n\n[d]: chart:daily')
        expect(summary.slice(parsed.sections[0].bodyOffset)).toMatch(/^\[Daily\]\[d\]/)
    })

    it('treats an empty or missing summary as an empty lead', () => {
        expect(parseReportSummary(null)).toEqual({ lead: '', leadOffset: 0, sections: [] })
        expect(parseReportSummary('  \n')).toEqual({ lead: '', leadOffset: 0, sections: [] })
    })
})
