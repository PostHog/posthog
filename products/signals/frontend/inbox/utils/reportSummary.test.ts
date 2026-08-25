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

        expect(parseReportSummary(summary)).toEqual({ lead: summary, sections: [] })
    })

    it('keeps a deeper heading inside its section body', () => {
        const [section] = parseReportSummary('Lead.\n\n## Problem\n\n#### Detail\n\nMore.').sections

        expect(section.body).toEqual('#### Detail\n\nMore.')
    })

    it('appends reference definitions to every slice so chart links still resolve', () => {
        const summary = 'Lead [Daily][d].\n\n## Impact\n\n[Daily][d]\n\n[d]: chart:daily'
        const parsed = parseReportSummary(summary)

        expect(parsed.lead).toEqual('Lead [Daily][d].\n\n[d]: chart:daily')
        expect(parsed.sections[0].body).toEqual('[Daily][d]\n\n[d]: chart:daily')
        expect(summary.slice(parsed.sections[0].bodyOffset)).toMatch(/^\[Daily\]\[d\]/)
    })

    it('treats an empty or missing summary as an empty lead', () => {
        expect(parseReportSummary(null)).toEqual({ lead: '', sections: [] })
        expect(parseReportSummary('  \n')).toEqual({ lead: '', sections: [] })
    })
})
