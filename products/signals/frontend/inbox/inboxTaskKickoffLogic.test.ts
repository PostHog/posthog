import { makeReport } from './__mocks__/inboxMocks'
import { buildDiscussReportPrompt } from './inboxTaskKickoffLogic'
import { SignalReportStatus } from './types'

describe('buildDiscussReportPrompt', () => {
    const url = 'https://app.posthog.com/project/1/inbox/report-1'

    it('tells the agent to carry out actions for a surfaced report', () => {
        const prompt = buildDiscussReportPrompt(
            makeReport({ status: SignalReportStatus.READY }),
            url,
            'Create the alert the report recommends'
        )
        expect(prompt).toContain('carry the action out')
        expect(prompt).toContain(url)
    })

    it('pins the agent to answering for a suppressed report', () => {
        // Safety suppression means the report's own prose can carry the instructions the judge
        // rejected, and the Dismissed view still offers Ask AI — so the agent must not be told to
        // carry actions from that context out.
        const prompt = buildDiscussReportPrompt(
            makeReport({ status: SignalReportStatus.SUPPRESSED }),
            url,
            'Carry out the recommendation'
        )
        expect(prompt).toContain('Answer this question')
        expect(prompt).not.toContain('carry the action out')
    })
})
