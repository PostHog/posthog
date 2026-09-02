import { makeReport } from './__mocks__/inboxMocks'
import { buildDiscussReportPrompt } from './inboxTaskKickoffLogic'
import { SignalReportStatus } from './types'

describe('buildDiscussReportPrompt', () => {
    const url = 'https://app.posthog.com/project/1/inbox/report-1'

    it.each([SignalReportStatus.READY, SignalReportStatus.PENDING_INPUT])(
        'tells the agent to carry out actions for a %s report',
        (status) => {
            const prompt = buildDiscussReportPrompt(
                makeReport({ status }),
                url,
                'Create the alert the report recommends'
            )
            expect(prompt).toContain('carry the action out')
            expect(prompt).toContain(url)
        }
    )

    // Only judged, still-active reports may drive actions: pre-judgment statuses carry unjudged
    // pipeline content, suppressed/failed reports carry the content the judge rejected, and a
    // resolved report's persisted action suggestions would redo already-completed work.
    it.each([
        SignalReportStatus.POTENTIAL,
        SignalReportStatus.CANDIDATE,
        SignalReportStatus.IN_PROGRESS,
        SignalReportStatus.RESOLVED,
        SignalReportStatus.SUPPRESSED,
        SignalReportStatus.FAILED,
        SignalReportStatus.DELETED,
    ])('pins the agent to answering for a %s report', (status) => {
        const prompt = buildDiscussReportPrompt(makeReport({ status }), url, 'Carry out the recommendation')
        expect(prompt).toContain('Answer this question')
        expect(prompt).not.toContain('carry the action out')
    })

    it.each([
        // A fix is already in flight, so acting on the recommendations would duplicate it — the same
        // reason autostart and Create PR eligibility exclude already-addressed reports.
        ['an already-addressed report', makeReport({ status: SignalReportStatus.READY, already_addressed: true })],
        // null = the kickoff refetch could not confirm the report's current state; fail closed.
        ['an unconfirmed report state', null],
    ])('pins the agent to answering for %s', (_name, report) => {
        const prompt = buildDiscussReportPrompt(report, url, 'Carry out the recommendation')
        expect(prompt).toContain('Answer this question')
        expect(prompt).not.toContain('carry the action out')
    })
})
