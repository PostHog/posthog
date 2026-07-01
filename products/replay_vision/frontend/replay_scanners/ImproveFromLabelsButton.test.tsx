import { expectLogic } from 'kea-test-utils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
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
                        outcome: 'Verdict: no',
                        reasoning: 'closed the tab',
                        isCorrect: false,
                        feedback: 'should be yes',
                    },
                    { outcome: 'Verdict: yes', reasoning: 'completed payment', isCorrect: true, feedback: '' },
                ],
            })

            expect(message).toContain('Did the user abandon checkout?')
            expect(message).toContain('Sessions it got WRONG (1)')
            expect(message).toContain('What it should be: should be yes')
            expect(message).toContain('Sessions it got RIGHT (1)')
            expect(message).toContain('rewrite the scanner prompt')
            // Recording-derived text is flagged as untrusted to PostHog AI.
            expect(message).toContain('untrusted data')
        })

        it('truncates long reasoning so the batch prompt stays bounded', () => {
            const longReasoning = 'x'.repeat(500)
            const message = buildImproveFromLabelsMessage({
                scannerName: 's',
                scannerType: 'monitor',
                prompt: 'p',
                examples: [{ outcome: 'Verdict: no', reasoning: longReasoning, isCorrect: false, feedback: 'fix' }],
            })

            expect(message).not.toContain(longReasoning)
            expect(message).toContain('x'.repeat(280))
        })

        it('omits the wrong section when every labeled session was correct', () => {
            const message = buildImproveFromLabelsMessage({
                scannerName: 's',
                scannerType: 'monitor',
                prompt: 'p',
                examples: [{ outcome: 'Verdict: yes', reasoning: null, isCorrect: true, feedback: '' }],
            })

            expect(message).not.toContain('got WRONG')
            expect(message).toContain('Sessions it got RIGHT (1)')
        })
    })

    describe('improveFromLabelsLogic', () => {
        let logic: ReturnType<typeof improveFromLabelsLogic.build>

        beforeEach(() => {
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
                        my_label: { is_correct: false, feedback: 'should be yes' },
                        scanner_result: { model_output: { verdict: 'no', reasoning: 'closed the tab' } },
                    },
                ],
            })

            logic.actions.improveFromLabels('Checkout drop-off', 'monitor', 'Did the user abandon checkout?')
            await expectLogic(logic).toFinishAllListeners()

            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            const options = sidePanelStateLogic.values.selectedTabOptions ?? ''
            // No leading "!" — the message is seeded as a draft, not auto-run.
            expect(options.startsWith('!')).toBe(false)
            expect(options).toContain('Sessions it got WRONG (1)')
            expect(options).toContain('should be yes')
        })

        it('drops sessions that have no label instead of counting them as correct', async () => {
            ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({
                results: [
                    {
                        my_label: { is_correct: false, feedback: 'should be yes' },
                        scanner_result: { model_output: { verdict: 'no', reasoning: 'closed the tab' } },
                    },
                    { my_label: null, scanner_result: { model_output: { verdict: 'yes' } } },
                ],
            })

            logic.actions.improveFromLabels('Checkout drop-off', 'monitor', 'Did the user abandon checkout?')
            await expectLogic(logic).toFinishAllListeners()

            const options = sidePanelStateLogic.values.selectedTabOptions ?? ''
            expect(options).toContain('Sessions it got WRONG (1)')
            expect(options).not.toContain('got RIGHT')
        })

        it('does not open PostHog AI when there are no labeled sessions', async () => {
            ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({ results: [] })

            logic.actions.improveFromLabels('s', 'monitor', 'p')
            await expectLogic(logic).toFinishAllListeners()

            // `selectedTab` persists across tests, so assert no message was seeded instead.
            expect(sidePanelStateLogic.values.selectedTabOptions).toBeNull()
        })
    })
})
