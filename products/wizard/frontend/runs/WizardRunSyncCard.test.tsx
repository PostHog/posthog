import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { WizardRunSyncCard } from './WizardRunSyncCard'
import { WizardRunSyncRunPicker } from './WizardRunSyncRunPicker'

const run = {
    status: 'running',
    stage: 'executing_wizard',
    program: { name: 'PostHog setup' },
    workspace: { type: 'local_folder', project_name: 'example-project' },
    environment: 'local',
} as WizardRunApi

const tasks = [{ name: 'Install the SDK', status: 'running' }] as WizardRunTaskApi[]

describe('WizardRunSyncCard', () => {
    afterEach(cleanup)

    it('shows the current task only during the running stage', () => {
        const props = {
            run,
            tasks,
            elapsedSeconds: 10,
            onExpand: jest.fn(),
            onExpandIcon: jest.fn(),
            onClose: jest.fn(),
            onHide: jest.fn(),
        }
        const { rerender } = render(<WizardRunSyncCard {...props} />)

        expect(screen.getByText('Install the SDK')).toBeTruthy()

        rerender(<WizardRunSyncCard {...props} run={{ ...run, stage: 'creating_artifacts' }} />)
        expect(screen.queryByText('Install the SDK')).toBeNull()

        rerender(<WizardRunSyncCard {...props} run={{ ...run, status: 'completed', stage: null }} />)
        expect(screen.getByText('Completed successfully')).toBeTruthy()
        expect(screen.queryByText('Install the SDK')).toBeNull()
    })

    it('switches to a different run without restarting the selected run', () => {
        const currentRun = { ...run, id: 'current', created_at: '2026-01-01T10:00:00Z' }
        const otherRun = {
            ...currentRun,
            id: 'other',
            status: 'completed' as const,
            workspace: { type: 'local_folder' as const, project_name: 'other-project' },
        }
        const onSelect = jest.fn()
        render(
            <WizardRunSyncRunPicker
                runs={[currentRun, otherRun]}
                activeCount={1}
                currentRunId={currentRun.id}
                onSelect={onSelect}
                onOpen={jest.fn()}
            />
        )

        const trigger = screen.getByLabelText('Switch Wizard run, 2 recent runs, 1 active runs')
        fireEvent.click(trigger)
        expect(screen.getByText('Completed')).toBeTruthy()
        expect(screen.getByText('In progress')).toBeTruthy()
        fireEvent.click(screen.getByText('example-project'))
        expect(onSelect).not.toHaveBeenCalled()

        fireEvent.click(trigger)
        fireEvent.click(screen.getByText('other-project'))
        expect(onSelect).toHaveBeenCalledWith(otherRun)
    })
})
