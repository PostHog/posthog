import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import type { WizardRunApi } from '../../generated/api.schemas'
import { WizardRunSidebarWidgetView } from './WizardRunSidebarWidgetView'

const runs: WizardRunApi[] = ['PostHog integration', 'Analytics audit', 'Error tracking audit'].map((name, index) => ({
    id: `run-${index}`,
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'local',
    workspace: { type: 'local_folder', project_name: 'example-project' },
    program: {
        id: name,
        name,
        description: '',
        command: [],
        wizard_version: '1.0.0',
        tags: [],
        required_programs: [],
        supported_environments: ['local'],
    },
    status: 'completed',
    stage: null,
    error_code: null,
    error_message: null,
    created_at: '2026-09-23T10:00:00Z',
    updated_at: null,
    started_at: null,
    finished_at: null,
    deadline_at: null,
}))

function Sidebar({
    onDismiss,
    onStateClick,
}: {
    onDismiss: (ids: string[]) => void
    onStateClick: () => void
}): JSX.Element {
    const [remaining, setRemaining] = useState(runs)
    return (
        <WizardRunSidebarWidgetView
            runs={remaining}
            onStateClick={onStateClick}
            onDismissRuns={(ids) => {
                onDismiss(ids)
                setRemaining((current) => current.filter((run) => !ids.includes(run.id)))
            }}
        />
    )
}

describe('WizardRunSidebarWidgetView', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('dismisses a selection together and keeps the panel open for the remaining run', async () => {
        const dismiss = jest.fn()
        const click = jest.fn()
        render(<Sidebar onDismiss={dismiss} onStateClick={click} />)
        expect(screen.getByText('3 completed')).toBeInTheDocument()
        expect(screen.queryByText('Wizard runs (3)')).not.toBeInTheDocument()
        fireEvent.click(screen.getByText('PostHog integration'))
        const panel = await screen.findByRole('dialog')
        fireEvent.click(within(panel).getByLabelText('Select PostHog integration'))
        fireEvent.click(within(panel).getByLabelText('Select Analytics audit'))
        fireEvent.click(within(panel).getByText('Dismiss selected (2)'))
        expect(dismiss).toHaveBeenLastCalledWith(['run-0', 'run-1'])
        expect(within(panel).queryByText('Analytics audit')).not.toBeInTheDocument()
        expect(within(panel).getByText('Error tracking audit')).toBeInTheDocument()
        expect(within(panel).getByText('Error tracking audit').closest('a')).toHaveAttribute(
            'href',
            `/project/${MOCK_DEFAULT_TEAM.id}/wizard/runs?run=run-2`
        )
        fireEvent.click(within(panel).getByLabelText('Dismiss Error tracking audit'))
        expect(dismiss).toHaveBeenLastCalledWith(['run-2'])
        expect(document.querySelector('[data-attr="wizard-run-sidebar-widget"]')).not.toBeInTheDocument()
        expect(click).toHaveBeenCalledTimes(1)
    })

    it('dismisses all runs directly from the card', () => {
        const dismiss = jest.fn()
        const click = jest.fn()
        render(<Sidebar onDismiss={dismiss} onStateClick={click} />)
        fireEvent.click(screen.getByLabelText('Dismiss all runs'))
        expect(dismiss).toHaveBeenCalledWith(runs.map((run) => run.id))
        expect(document.querySelector('[data-attr="wizard-run-sidebar-widget"]')).not.toBeInTheDocument()
        expect(click).not.toHaveBeenCalled()
    })

    it('tracks the single-run card click while preserving its run link', () => {
        const click = jest.fn()
        render(<WizardRunSidebarWidgetView runs={[runs[0]]} onStateClick={click} onDismissRuns={jest.fn()} />)
        const link = screen.getByText('PostHog integration').closest('a')!
        expect(link).toHaveAttribute('href', `/project/${MOCK_DEFAULT_TEAM.id}/wizard/runs?run=run-0`)
        fireEvent.click(link)
        expect(click).toHaveBeenCalledTimes(1)
    })

    it('shows the current program and activity without assuming an installation', () => {
        const audit = { ...runs[1], status: 'running' as const, stage: 'executing_wizard' as const }
        render(
            <WizardRunSidebarWidgetView
                runs={[audit, { ...runs[2], status: 'failed' }]}
                tasksByRunId={{
                    [audit.id]: [
                        {
                            name: 'Checking event coverage',
                            status: 'running',
                            created_at: '2026-09-23T10:00:00Z',
                            started_at: null,
                            completed_at: null,
                            failed_at: null,
                            error_message: null,
                        },
                    ],
                }}
                onDismissRuns={jest.fn()}
                initialHovered
            />
        )
        expect(screen.getByText('Analytics audit')).toBeInTheDocument()
        expect(screen.getByText('Checking event coverage')).toBeInTheDocument()
        expect(screen.getByText('1 running')).toBeInTheDocument()
        expect(screen.getByText('1 failed')).toBeInTheDocument()
    })
})
