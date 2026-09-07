import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { SignalScoutRunSummary } from '../../../types'
import { ScoutRunBoxes } from './ScoutRunBoxes'

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        skill_name: 'signals-scout-general',
        skill_version: 1,
        status: 'completed',
        metadata: {},
        created_at: '2026-07-22T01:00:00Z',
        started_at: '2026-07-22T01:00:00Z',
        completed_at: '2026-07-22T01:02:00Z',
        summary: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

describe('ScoutRunBoxes', () => {
    afterEach(() => {
        cleanup()
    })

    it('states what a run cost, and stays silent about runs with no cost', () => {
        // The strip is the only place a person can see what one scout run spent, so a cost that
        // reaches the logic but not the box says nothing to anyone.
        const { container } = render(
            <ScoutRunBoxes
                runs={[makeRun({ run_id: 'run-priced' }), makeRun({ run_id: 'run-unpriced' })]}
                costs={new Map([['run-priced', 4.03]])}
            />
        )

        const labels = Array.from(container.querySelectorAll('.sr-only')).map((node) => node.textContent ?? '')
        expect(labels.filter((label) => label.includes('$4.03'))).toHaveLength(1)
        expect(labels.filter((label) => label.includes('$'))).toHaveLength(1)
    })

    it('leaves every run unpriced when no costs are given', () => {
        const { container } = render(<ScoutRunBoxes runs={[makeRun()]} />)

        expect(container.querySelector('.sr-only')?.textContent).not.toContain('$')
    })
})
