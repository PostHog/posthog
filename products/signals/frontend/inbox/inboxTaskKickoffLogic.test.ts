import { makeReport } from './__mocks__/inboxMocks'
import { buildCreatePrReportPrompt, buildDiscussReportPrompt } from './inboxTaskKickoffLogic'
import { SignalReportStatus } from './types'

describe('inboxTaskKickoffLogic', () => {
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
                expect(prompt).toContain('inbox-reports-set-state')
                // A discussion run can open a PR too, so it carries the Create PR prompt's guard: a
                // resolve through the state API closes the report's open PR.
                expect(prompt).toContain('would close the PR you just opened')
                // The state API has no ownership precondition, so the prompt is the only thing keeping
                // a discussion run from ending work another run holds.
                expect(prompt).toContain('leave its state alone when somebody else holds it')
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
            // An answer-only run changes nothing about the report, so it is never told to touch the state.
            expect(prompt).not.toContain('inbox-reports-set-state')
        })

        it.each([
            // A fix is already in flight, so acting on the recommendations would duplicate it — the same
            // reason autostart and Create PR eligibility exclude already-addressed reports.
            ['an already-addressed report', makeReport({ status: SignalReportStatus.READY, already_addressed: true })],
            // The actionability judge said there is no work to act on, so an action framing would invite
            // acting anyway — the same judgment that hides Create PR.
            [
                'a report judged not actionable',
                makeReport({ status: SignalReportStatus.READY, actionability: 'not_actionable' }),
            ],
            // An implementation PR already exists for this report, so carrying a stored "implement the
            // fix" suggestion out would open a second PR for the same work — the same field that hides
            // Create PR.
            [
                'a report with an implementation PR',
                makeReport({
                    status: SignalReportStatus.READY,
                    implementation_pr_url: 'https://github.com/x/y/pull/1',
                }),
            ],
            // null = the kickoff refetch could not confirm the report's current state; fail closed.
            ['an unconfirmed report state', null],
        ])('pins the agent to answering for %s', (_name, report) => {
            const prompt = buildDiscussReportPrompt(report, url, 'Carry out the recommendation')
            expect(prompt).toContain('Answer this question')
            expect(prompt).not.toContain('carry the action out')
        })
    })

    describe('buildCreatePrReportPrompt', () => {
        it('tells the agent how to leave the report state', () => {
            const prompt = buildCreatePrReportPrompt(makeReport({ status: SignalReportStatus.READY }))
            expect(prompt).toContain('open a PR')
            expect(prompt).toContain('inbox-reports-set-state')
            expect(prompt).toContain('fixed_outside_posthog')
            expect(prompt).toContain('suppressed')
            // Suppressing leaves the claim standing, so the run has to drop it itself.
            expect(prompt).toContain('then release your claim')
            // The claim is taken once, at task creation, so a rerun starts unclaimed.
            expect(prompt).toContain('claim it again first')
            // Resolving through the state API closes the report's open PR, so the run must not report
            // the PR it just opened as a resolution.
            expect(prompt).toContain('Do NOT set the state to resolved because you opened a PR')
        })

        it('keeps the user feedback after the state instructions', () => {
            const prompt = buildCreatePrReportPrompt(
                makeReport({ status: SignalReportStatus.READY }),
                'check the retries'
            )
            expect(prompt.indexOf('inbox-reports-set-state')).toBeLessThan(prompt.indexOf('check the retries'))
        })
    })
})
