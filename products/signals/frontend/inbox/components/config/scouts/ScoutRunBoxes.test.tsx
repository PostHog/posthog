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

    it('marks the runs at or over the fleet threshold, and leaves the cheap ones plain', () => {
        // Cost only reached the tooltip, so finding an expensive run meant hovering box by box.
        // The marker is the whole point of the change: without it every box looks the same.
        const { container } = render(
            <ScoutRunBoxes
                runs={[
                    makeRun({ run_id: 'run-cheap' }),
                    makeRun({ run_id: 'run-at' }),
                    makeRun({ run_id: 'run-over' }),
                ]}
                costs={
                    new Map([
                        ['run-cheap', 0.05],
                        ['run-at', 0.49],
                        ['run-over', 3.19],
                    ])
                }
                costThreshold={0.49}
            />
        )

        expect(container.querySelectorAll('.bg-brand-yellow')).toHaveLength(2)
        const labels = Array.from(container.querySelectorAll('.sr-only')).map((node) => node.textContent ?? '')
        expect(labels.filter((label) => label.includes('top 10% of runs by cost'))).toHaveLength(2)
    })

    it('puts the marker inside the task link, so the whole column opens the task run', () => {
        // The tooltip covers the column and offers to open the task run, and the column reserves
        // height above the box for the marker. With the link around the box alone, a click on the
        // marker does nothing on a roster card, and the roster table's row handler sends the
        // reader to the scout page instead.
        const { container } = render(
            <ScoutRunBoxes
                runs={[makeRun({ run_id: 'run-over', task_url: '/project/2/tasks/run-over' })]}
                costs={new Map([['run-over', 3.19]])}
                costThreshold={0.49}
            />
        )

        const link = container.querySelector('a')
        expect(link).toHaveAttribute('href', '/project/2/tasks/run-over')
        expect(link?.querySelector('.bg-brand-yellow')).not.toBeNull()
    })

    it('marks nothing while the fleet has too few priced runs to rank', () => {
        const { container } = render(
            <ScoutRunBoxes runs={[makeRun()]} costs={new Map([['run-1', 3.19]])} costThreshold={null} />
        )

        expect(container.querySelector('.bg-brand-yellow')).toBeNull()
    })

    it('leaves every run unpriced when no costs are given', () => {
        const { container } = render(<ScoutRunBoxes runs={[makeRun()]} />)

        expect(container.querySelector('.sr-only')?.textContent).not.toContain('$')
    })
})
