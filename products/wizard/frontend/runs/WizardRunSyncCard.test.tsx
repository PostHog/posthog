import { render, screen } from '@testing-library/react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { WizardRunSyncCard } from './WizardRunSyncCard'

const run = {
    status: 'running',
    stage: 'executing_wizard',
    program: { name: 'PostHog setup' },
    workspace: { type: 'local_folder', project_name: 'example-project' },
    environment: 'local',
} as WizardRunApi

const tasks = [{ name: 'Install the SDK', status: 'running' }] as WizardRunTaskApi[]

describe('WizardRunSyncCard', () => {
    it('shows the current task only during the running stage', () => {
        const props = {
            run,
            tasks,
            activeCount: 1,
            elapsedSeconds: 10,
            onExpand: jest.fn(),
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
})
