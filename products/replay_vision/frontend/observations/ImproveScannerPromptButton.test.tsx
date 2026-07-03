import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { initKeaTests } from '~/test/init'
import { SidePanelTab } from '~/types'

import type { ReplayObservationApi } from '../generated/api.schemas'
import {
    ImproveScannerPromptButton,
    buildImproveScannerPromptMessage,
    describeObservationOutcome,
} from './ImproveScannerPromptButton'

const observationWithOutput = (modelOutput: Record<string, unknown>): ReplayObservationApi =>
    ({ scanner_result: { model_output: modelOutput, signals_count: 0 } }) as unknown as ReplayObservationApi

describe('ImproveScannerPromptButton', () => {
    describe('describeObservationOutcome', () => {
        it.each([
            ['a monitor verdict', { verdict: 'no' }, 'Verdict: no'],
            ['a scorer score', { score: 3 }, 'Score: 3'],
            ['classifier tags', { tags: ['billing', 'churn'] }, 'Tags: billing, churn'],
            ['nothing to report', { summary: 'a summary' }, null],
        ])('summarizes %s', (_label, modelOutput, expected) => {
            expect(describeObservationOutcome(observationWithOutput(modelOutput))).toBe(expected)
        })
    })

    describe('buildImproveScannerPromptMessage', () => {
        it('includes the prompt, outcome, reasoning, session ID and a rewrite instruction', () => {
            const message = buildImproveScannerPromptMessage({
                scannerName: 'Checkout drop-off',
                scannerType: 'monitor',
                prompt: 'Did the user abandon checkout?',
                sessionId: 'sess-1',
                outcome: 'Verdict: no',
                reasoning: 'The user closed the tab on the payment step.',
            })

            expect(message).toContain('Checkout drop-off')
            expect(message).toContain('Scanner type: monitor')
            expect(message).toContain('Did the user abandon checkout?')
            expect(message).toContain('Result on this session: Verdict: no')
            expect(message).toContain("Model's reasoning: The user closed the tab on the payment step.")
            expect(message).toContain('rewrite the scanner prompt')
            // The session ID lets PostHog AI look up and summarize the recording for more context.
            expect(message).toContain('Session ID: sess-1')
            // Recording-derived text is flagged as untrusted to PostHog AI.
            expect(message).toContain('untrusted data')
        })

        it('omits the outcome and reasoning lines when absent', () => {
            const message = buildImproveScannerPromptMessage({
                scannerName: 'Session summary',
                scannerType: 'summarizer',
                prompt: 'Summarize the user goal.',
                sessionId: 'sess-1',
            })

            expect(message).not.toContain('Result on this session:')
            expect(message).not.toContain("Model's reasoning:")
        })
    })

    describe('component', () => {
        beforeEach(() => {
            initKeaTests()
            sidePanelStateLogic.mount()
        })

        afterEach(() => {
            cleanup()
        })

        it('seeds PostHog AI with the prompt, outcome and reasoning as a draft (no auto-run)', () => {
            render(
                <Provider>
                    <ImproveScannerPromptButton
                        scannerName="Checkout drop-off"
                        scannerType="monitor"
                        prompt="Did the user abandon checkout?"
                        sessionId="sess-1"
                        outcome="Verdict: no"
                        reasoning="The user closed the tab on the payment step."
                    />
                </Provider>
            )

            fireEvent.click(screen.getByText('Improve prompt'))

            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            const options = sidePanelStateLogic.values.selectedTabOptions ?? ''
            // No leading "!" — the message is seeded as a draft, not auto-run.
            expect(options.startsWith('!')).toBe(false)
            expect(options).toContain('Did the user abandon checkout?')
            expect(options).toContain('Result on this session: Verdict: no')
            expect(options).toContain('The user closed the tab on the payment step.')
        })
    })
})
