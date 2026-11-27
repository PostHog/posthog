import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'

import { initKeaTests } from '~/test/init'

import type { WizardRunApi } from '../../generated/api.schemas'
import { WizardRunTable } from './WizardRunTable'

const run: WizardRunApi = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: 1,
    created_by_id: 1,
    created_by: null,
    environment: 'cloud',
    workspace: { type: 'git_repository', repository: 'example/project' },
    program: {
        id: 'posthog-integration',
        name: 'PostHog integration',
        description: '',
        command: [],
        wizard_version: '1.0.0',
        tags: [],
        required_programs: [],
        supported_environments: ['cloud'],
    },
    status: 'running',
    stage: 'executing_wizard',
    error_code: null,
    error_message: null,
    created_at: '2026-01-01T10:00:00Z',
    updated_at: null,
    started_at: null,
    finished_at: null,
    deadline_at: null,
}

describe('WizardRunTable', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('keeps the actions menu open across refreshes and uses the latest run, state and callbacks', async () => {
        const props: ComponentProps<typeof WizardRunTable> = {
            runs: [run],
            totalRuns: 1,
            currentUserId: 1,
            loading: false,
            failed: false,
            hasActiveFilters: false,
            refreshing: false,
            cancelling: false,
            onOpenLibrary: jest.fn(),
            onClearFilters: jest.fn(),
            onRefreshRuns: jest.fn(),
            onSelect: jest.fn(),
            onRefreshRun: jest.fn(),
            onCopyRunId: jest.fn(),
            onOpenWorkspace: jest.fn(),
            onPaginate: jest.fn(),
            onCancel: jest.fn(),
        }
        const { rerender } = render(<WizardRunTable {...props} />)
        fireEvent.click(screen.getByLabelText('More options for PostHog integration'))
        const menu = await screen.findByRole('menu')
        expect(within(menu).getByText('Cancel run')).not.toHaveAttribute('aria-disabled', 'true')

        const refreshedRun: WizardRunApi = { ...run, program: { ...run.program }, stage: 'creating_artifacts' }
        const onSelect = jest.fn()
        rerender(
            <WizardRunTable
                {...props}
                runs={[refreshedRun]}
                refreshing
                cancelling
                highlightedRunId={run.id}
                onSelect={onSelect}
            />
        )
        expect(menu).toBeInTheDocument()
        expect(within(menu).getByText('Refreshing…')).toHaveAttribute('aria-disabled', 'true')
        expect(within(menu).getByText('Canceling…')).toHaveAttribute('aria-disabled', 'true')

        rerender(<WizardRunTable {...props} runs={[refreshedRun]} currentUserId={null} onSelect={onSelect} />)
        expect(menu).toBeInTheDocument()
        expect(within(menu).getByText('Refresh status')).not.toHaveAttribute('aria-disabled', 'true')
        expect(within(menu).queryByText('Cancel run')).not.toBeInTheDocument()
        fireEvent.click(within(menu).getByText('View run details'))
        expect(onSelect).toHaveBeenCalledWith(refreshedRun)
        expect(props.onSelect).not.toHaveBeenCalled()

        fireEvent.click(screen.getByLabelText('More options for PostHog integration'))
        const reopenedMenu = await screen.findByRole('menu')
        rerender(<WizardRunTable {...props} runs={[{ ...refreshedRun, id: 'replacement-run' }]} />)
        expect(reopenedMenu).not.toBeInTheDocument()
    })
})
