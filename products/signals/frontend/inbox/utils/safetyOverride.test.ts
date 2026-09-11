import { makeReport } from '../__mocks__/inboxMocks'
import { SignalReportArtefact, SignalReportStatus } from '../types'
import { latestUnsafeSafetyExplanation, safetyOverrideReason } from './safetyOverride'

function judgment(overrides: Partial<SignalReportArtefact> & { content: Record<string, any> }): SignalReportArtefact {
    return {
        id: 'artefact-1',
        type: 'safety_judgment',
        created_at: '2026-06-11T10:00:00Z',
        ...overrides,
    }
}

describe('safetyOverride', () => {
    describe('latestUnsafeSafetyExplanation', () => {
        // The confirmation exists to quote the verdict the person is overruling, and the newest row
        // of a status type is the canonical one. Reading an older row would quote a verdict that no
        // longer applies, and reading a *safe* row as a rejection would tell a person their own
        // earlier override was PostHog refusing the report.
        it.each([
            {
                name: 'the newest unsafe verdict, whatever order the API returned them in',
                artefacts: [
                    judgment({
                        id: 'old',
                        created_at: '2026-06-11T10:00:00Z',
                        content: { choice: false, explanation: 'Stale reason' },
                    }),
                    judgment({
                        id: 'new',
                        created_at: '2026-06-12T10:00:00Z',
                        content: { choice: false, explanation: 'Current reason' },
                    }),
                ],
                expected: 'Current reason',
            },
            {
                name: 'nothing when the newest verdict approves the report',
                artefacts: [
                    judgment({
                        id: 'old',
                        created_at: '2026-06-11T10:00:00Z',
                        content: { choice: false, explanation: 'Stale reason' },
                    }),
                    judgment({
                        id: 'new',
                        created_at: '2026-06-12T10:00:00Z',
                        content: { choice: true, explanation: 'Overridden by user 7' },
                    }),
                ],
                expected: null,
            },
            {
                name: 'nothing when the verdict left no explanation',
                artefacts: [judgment({ content: { choice: false } })],
                expected: null,
            },
            {
                name: 'nothing when the report carries no verdict',
                artefacts: [{ id: 'a', type: 'priority_judgment', content: {}, created_at: '2026-06-11T10:00:00Z' }],
                expected: null,
            },
            { name: 'nothing when the artefacts never loaded', artefacts: null, expected: null },
        ])('returns $name', ({ artefacts, expected }) => {
            expect(latestUnsafeSafetyExplanation(artefacts)).toBe(expected)
        })
    })

    describe('safetyOverrideReason', () => {
        // The reason is the whole point of the confirmation, so a report with no quotable verdict
        // must still say something true about why PostHog stopped, rather than falling back to the
        // "not researched yet" line for a report that was researched and rejected.
        it('quotes the safety verdict when there is one', () => {
            const reason = safetyOverrideReason(
                makeReport({ status: SignalReportStatus.SUPPRESSED }),
                'The signals ask for a safety control to be removed.'
            )

            expect(reason).toContain('safety check flagged')
            expect(reason).toContain('The signals ask for a safety control to be removed.')
        })

        it.each([
            [SignalReportStatus.FAILED, 'The run that researched it failed.'],
            [SignalReportStatus.SUPPRESSED, 'This report is dismissed'],
            [SignalReportStatus.POTENTIAL, "hasn't researched this report yet"],
            [SignalReportStatus.CANDIDATE, "hasn't researched this report yet"],
        ])('falls back to what a %s report can say', (status, expected) => {
            expect(safetyOverrideReason(makeReport({ status }), null)).toContain(expected)
        })
    })
})
