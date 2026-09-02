import { makeReport } from '../__mocks__/inboxMocks'
import { buildCreatePrReportPrompt } from './kickoffPrompts'

describe('kickoffPrompts', () => {
    // The PR this run opens is the only thing the reviewer sees, and it carries none of the report's
    // evidence — so losing the link strands them with a diff and no reason for it. This path had no
    // link at all until it was added, which is exactly how quietly it goes missing.
    it('tells the agent to link back to the report', () => {
        const prompt = buildCreatePrReportPrompt(makeReport({ id: 'report-7' }))

        expect(prompt).toContain('/inbox/reports/report-7')
        expect(prompt).toContain('this inbox report')
    })

    // The prompt reaches a public repository; the validation prompt may name a replica or an
    // internal dashboard. Adding it here "to help the agent reproduce" is the plausible mistake.
    it('leaves the local validation prompt out of the run', () => {
        const prompt = buildCreatePrReportPrompt(
            makeReport({ validation_prompt: 'Run EXPLAIN against replica-internal-7.' })
        )

        expect(prompt).not.toContain('replica-internal-7')
    })

    it('appends a typed note as extra feedback', () => {
        const prompt = buildCreatePrReportPrompt(makeReport(), '  Put the fix behind a flag.  ')

        expect(prompt).toContain('Additional feedback from the user')
        expect(prompt).toContain('Put the fix behind a flag.')
    })
})
