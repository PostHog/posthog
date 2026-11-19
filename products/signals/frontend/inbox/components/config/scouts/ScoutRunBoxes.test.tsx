import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render } from '@testing-library/react'

import { SignalScoutRunSummary } from '../../../types'
import { ScoutRunBoxes } from './ScoutRunBoxes'

function makeRun(overrides: Partial<SignalScoutRunSummary> = {}): SignalScoutRunSummary {
    return {
        run_id: 'run-1',
        total_spend: null,
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

        const labels = Array.from(container.querySelectorAll('[aria-label]')).map(
            (node) => node.getAttribute('aria-label') ?? ''
        )
        expect(labels.filter((label) => label.includes('403 credits'))).toHaveLength(1)
        expect(labels.filter((label) => label.includes('credits'))).toHaveLength(1)
    })

    it('renders two elements per plain run, so a large fleet stays a small DOM', () => {
        // The roster renders one strip per scout. An extra node per box multiplies by every run on
        // every card, and a filter change discards the whole set at once.
        const runs = Array.from({ length: 24 }, (_, i) => makeRun({ run_id: `run-${i}` }))
        const { container } = render(<ScoutRunBoxes runs={runs} />)

        const strip = container.firstElementChild as HTMLElement
        expect(strip.querySelectorAll('*')).toHaveLength(runs.length * 2)
    })

    it('shows the hovered run in one tooltip, and closes it on Escape or when the pointer leaves the box', () => {
        jest.useFakeTimers()
        try {
            const { container } = render(
                <ScoutRunBoxes
                    runs={[
                        makeRun({ run_id: 'run-plain', status: 'failed' }),
                        makeRun({ run_id: 'run-linked', task_url: '/project/2/tasks/run-linked' }),
                    ]}
                />
            )
            expect(document.querySelector('.Tooltip')).toBeNull()

            fireEvent.mouseOver(container.querySelector('[data-run-id="run-linked"]') as Element)
            act(() => {
                jest.advanceTimersByTime(400)
            })

            const tooltips = document.querySelectorAll('.Tooltip')
            expect(tooltips).toHaveLength(1)
            expect(tooltips[0]).toHaveTextContent('open task run')

            fireEvent.keyDown(document, { key: 'Escape' })
            act(() => {
                jest.advanceTimersByTime(400)
            })
            expect(document.querySelector('.Tooltip')).toBeNull()

            fireEvent.mouseOver(container.querySelector('[data-run-id="run-plain"]') as Element)
            fireEvent.mouseOver(container.firstElementChild as Element)
            act(() => {
                jest.advanceTimersByTime(400)
            })
            expect(document.querySelector('.Tooltip')).toBeNull()
        } finally {
            jest.useRealTimers()
        }
    })

    it('leaves every run unpriced when no costs are given', () => {
        const { container } = render(<ScoutRunBoxes runs={[makeRun()]} />)

        expect(container.querySelector('[aria-label]')?.getAttribute('aria-label')).not.toContain('credits')
    })
})
