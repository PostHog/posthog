import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type { SignalNode } from 'scenes/debug/signals/types'

import { isSignalsScoutExtra, SignalsScoutSignalCard } from './SignalsScoutSignalCard'

jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

function makeSignal(extra: Record<string, unknown>): SignalNode {
    return {
        signal_id: 'signal-1',
        content: 'Checkout 500s spike after the payment flag rollout',
        source_product: 'signals_scout',
        source_type: 'cross_source_issue',
        source_id: 'run:run-1:finding:finding-1',
        weight: 1,
        timestamp: '2026-07-13T00:00:00Z',
        extra: {
            scout_run_id: 'run-1',
            task_run_id: 'task-run-1',
            finding_id: 'finding-1',
            skill_name: 'signals-scout-error-tracking',
            skill_version: 3,
            evidence: [{ source_product: 'error_tracking', summary: '500s on /checkout quadrupled', entity_id: 'abc' }],
            ...extra,
        },
    }
}

describe('SignalsScoutSignalCard', () => {
    afterEach(cleanup)

    // `confidence` was retired from the emit contract, so a finding emitted without it must still
    // route to this card rather than falling back to the generic one.
    it.each([
        ['without a confidence', {}],
        ['with a legacy confidence', { confidence: 0.9 }],
    ])('recognises and renders a scout finding %s', (_name, extra) => {
        const signal = makeSignal(extra)

        expect(isSignalsScoutExtra(signal.extra)).toBe(true)

        const { container } = render(<SignalsScoutSignalCard signal={signal} />)

        expect(screen.getByText('500s on /checkout quadrupled')).toBeInTheDocument()
        expect(container).not.toHaveTextContent('Confidence')
    })
})
