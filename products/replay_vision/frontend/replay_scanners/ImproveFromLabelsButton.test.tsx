import { expectLogic } from 'kea-test-utils'

import { SIDE_PANEL_PANEL_ID, maxLogic } from 'scenes/max/maxLogic'
import { maxMocks } from 'scenes/max/testUtils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import { visionScannersObservationsList } from '../generated/api'
import { buildImproveFromLabelsMessage, improveFromLabelsLogic } from './ImproveFromLabelsButton'

jest.mock('../generated/api', () => ({ visionScannersObservationsList: jest.fn() }))

describe('ImproveFromLabelsButton', () => {
    describe('buildImproveFromLabelsMessage', () => {
        it('groups wrong and correct sessions, carries feedback and a rewrite instruction', () => {
            const message = buildImproveFromLabelsMessage({
                scannerName: 'Checkout drop-off',
                scannerType: 'monitor',
                prompt: 'Did the user abandon checkout?',
                examples: [
                    {
                        sessionId: 'sess-wrong',
                        outcome: 'Verdict: no',
                        reasoning: 'closed the tab',
                        isCorrect: false,
                        feedback: 'should be yes',
                    },
                    {
                        sessionId: 'sess-right',
                        outcome: 'Verdict: yes',
                        reasoning: 'completed payment',
                        isCorrect: true,
                        feedback: 'correctly caught the confirmation page',
                    },
                ],
            })

            expect(message).toContain('Did the user abandon checkout?')
            expect(message).toContain('Sessions it got WRONG (1)')
            expect(message).toContain('What it should be: should be yes')
            expect(message).toContain('Sessions it got RIGHT (1)')
            // Feedback is optional on thumbs-up sessions too, carried as a note.
            expect(message).toContain('Note: correctly caught the confirmation page')
            expect(message).toContain('rewrite the scanner prompt')
            // Session IDs let PostHog AI look up and summarize the recordings for more context.
            expect(message).toContain('Session sess-wrong')
            expect(message).toContain('Session sess-right')
            // Recording-derived text is flagged as untrusted to PostHog AI.
            expect(message).toContain('untrusted data')
        })

        it('truncates long reasoning so the batch prompt stays bounded', () => {
            const longReasoning = 'x'.repeat(500)
            const message = buildImproveFromLabelsMessage({
                scannerName: 's',
                scannerType: 'monitor',
                prompt: 'p',
                examples: [
                    {
                        sessionId: 'sess-1',
                        outcome: 'Verdict: no',
                        reasoning: longReasoning,
                        isCorrect: false,
                        feedback: 'fix',
                    },
                ],
            })

            expect(message).not.toContain(longReasoning)
            expect(message).toContain('x'.repeat(280))
        })

        it('omits the wrong section when every labeled session was correct', () => {
            const message = buildImproveFromLabelsMessage({
                scannerName: 's',
                scannerType: 'monitor',
                prompt: 'p',
                examples: [
                    { sessionId: 'sess-1', outcome: 'Verdict: yes', reasoning: null, isCorrect: true, feedback: '' },
                ],
            })

            expect(message).not.toContain('got WRONG')
            expect(message).toContain('Sessions it got RIGHT (1)')
        })
    })

    describe('improveFromLabelsLogic', () => {
        let logic: ReturnType<typeof improveFromLabelsLogic.build>

        beforeEach(() => {
            useMocks(maxMocks)
            initKeaTests()
            sidePanelStateLogic.mount()
            logic = improveFromLabelsLogic({ scannerId: 'scan-1' })
            logic.mount()
        })

        afterEach(() => {
            logic?.unmount()
        })

        it('seeds PostHog AI with the labeled sessions as a draft (no auto-run)', async () => {
            ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({
                results: [
                    {
                        session_id: 'sess-wrong',
                        label: { is_correct: false, feedback: 'should be yes' },
                        scanner_result: { model_output: { verdict: 'no', reasoning: 'closed the tab' } },
                    },
                ],
            })

            logic.actions.improveFromLabels('Checkout drop-off', 'monitor', 'Did the user abandon checkout?')
            await expectLogic(logic).toFinishAllListeners()

            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            // The options mirror into the #panel URL hash, so the session-ID-bearing draft must not be there.
            expect(sidePanelStateLogic.values.selectedTabOptions || null).toBeNull()
            const question = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })?.values.question ?? ''
            // No leading "!" — the message is seeded as a draft, not auto-run.
            expect(question.startsWith('!')).toBe(false)
            expect(question).toContain('Sessions it got WRONG (1)')
            expect(question).toContain('Session sess-wrong')
            expect(question).toContain('should be yes')
        })

        it('drops sessions that have no label instead of counting them as correct', async () => {
            ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({
                results: [
                    {
                        label: { is_correct: false, feedback: 'should be yes' },
                        scanner_result: { model_output: { verdict: 'no', reasoning: 'closed the tab' } },
                    },
                    { label: null, scanner_result: { model_output: { verdict: 'yes' } } },
                ],
            })

            logic.actions.improveFromLabels('Checkout drop-off', 'monitor', 'Did the user abandon checkout?')
            await expectLogic(logic).toFinishAllListeners()

            const question = maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })?.values.question ?? ''
            expect(question).toContain('Sessions it got WRONG (1)')
            expect(question).not.toContain('got RIGHT')
        })

        it('does not open PostHog AI when there are no labeled sessions', async () => {
            ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({ results: [] })

            logic.actions.improveFromLabels('s', 'monitor', 'p')
            await expectLogic(logic).toFinishAllListeners()

            // `selectedTab` persists across tests, so assert no draft was seeded instead.
            expect(maxLogic.findMounted({ panelId: SIDE_PANEL_PANEL_ID })?.values.question ?? '').toBe('')
        })
    })
})
