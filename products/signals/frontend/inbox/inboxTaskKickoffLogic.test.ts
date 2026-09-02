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

    // A suppressed scout report's own prose can carry the instructions the judge rejected, and the
    // pipeline marks its safety rejections failed — both stay reachable with Ask AI, so the agent
    // must not be told to carry actions from that context out.
    it.each([SignalReportStatus.SUPPRESSED, SignalReportStatus.FAILED])(
        'pins the agent to answering for a %s report',
        (status) => {
            const prompt = buildDiscussReportPrompt(makeReport({ status }), url, 'Carry out the recommendation')
            expect(prompt).toContain('Answer this question')
            expect(prompt).not.toContain('carry the action out')
        }
    )
})
