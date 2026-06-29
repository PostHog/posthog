import '@testing-library/jest-dom'

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
        it('prefers a monitor verdict', () => {
            expect(describeObservationOutcome(observationWithOutput({ verdict: 'no' }))).toBe('Verdict: no')
        })

        it('falls back to a scorer score', () => {
            expect(describeObservationOutcome(observationWithOutput({ score: 3 }))).toBe('Score: 3')
        })

        it('falls back to classifier tags', () => {
            expect(describeObservationOutcome(observationWithOutput({ tags: ['billing', 'churn'] }))).toBe(
                'Tags: billing, churn'
            )
        })

        it('returns null when there is no verdict, score or tags', () => {
            expect(describeObservationOutcome(observationWithOutput({ summary: 'a summary' }))).toBeNull()
        })
    })

    describe('buildImproveScannerPromptMessage', () => {
        it('includes the prompt, outcome, reasoning and a rewrite instruction', () => {
            const message = buildImproveScannerPromptMessage({
                scannerName: 'Checkout drop-off',
                scannerType: 'monitor',
                prompt: 'Did the user abandon checkout?',
                outcome: 'Verdict: no',
                reasoning: 'The user closed the tab on the payment step.',
            })

            expect(message).toContain('Checkout drop-off')
            expect(message).toContain('Scanner type: monitor')
            expect(message).toContain('Did the user abandon checkout?')
            expect(message).toContain('Result on this session: Verdict: no')
            expect(message).toContain("Model's reasoning: The user closed the tab on the payment step.")
            expect(message).toContain('rewrite the scanner prompt')
        })

        it('omits the outcome and reasoning lines when absent', () => {
            const message = buildImproveScannerPromptMessage({
                scannerName: 'Session summary',
                scannerType: 'summarizer',
                prompt: 'Summarize the user goal.',
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

        it('opens PostHog AI with the prompt, outcome and reasoning, and auto-runs it', () => {
            render(
                <Provider>
                    <ImproveScannerPromptButton
                        scannerName="Checkout drop-off"
                        scannerType="monitor"
                        prompt="Did the user abandon checkout?"
                        outcome="Verdict: no"
                        reasoning="The user closed the tab on the payment step."
                    />
                </Provider>
            )

            fireEvent.click(screen.getByText('Ask PostHog AI to improve this prompt'))

            expect(sidePanelStateLogic.values.selectedTab).toBe(SidePanelTab.Max)
            const options = sidePanelStateLogic.values.selectedTabOptions ?? ''
            // Leading "!" tells PostHog AI to auto-run the message.
            expect(options.startsWith('!')).toBe(true)
            expect(options).toContain('Did the user abandon checkout?')
            expect(options).toContain('Result on this session: Verdict: no')
            expect(options).toContain('The user closed the tab on the payment step.')
        })
    })
})
