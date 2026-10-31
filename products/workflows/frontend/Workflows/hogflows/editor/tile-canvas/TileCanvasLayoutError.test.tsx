import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow } from '../../types'
import { TileCanvasLayoutError } from './TileCanvasLayoutError'
import { tileCanvasLogic } from './tileCanvasLogic'

jest.mock('lib/components/AppMetrics/appMetricsLogic', () => ({
    ...jest.requireActual('lib/components/AppMetrics/appMetricsLogic'),
    loadAppMetricsTotals: () => new Promise(() => {}),
}))

const WORKFLOW_ID = 'wf-layout-error-1'

const WORKFLOW = {
    id: WORKFLOW_ID,
    name: 'Layout error test',
    version: 1,
    status: 'draft',
    team_id: 1,
    exit_condition: 'exit_only_at_end',
    trigger: { type: 'event', filters: {} },
    actions: [
        { id: 'trigger_node', type: 'trigger', name: 'Trigger', config: { type: 'event', filters: {} } },
        { id: 'exit_node', type: 'exit', name: 'Exit', config: { reason: '' } },
    ],
    edges: [{ from: 'trigger_node', to: 'exit_node', type: 'continue' }],
    created_at: '2026-10-01T00:00:00.000Z',
    updated_at: '2026-10-01T00:00:00.000Z',
} as unknown as HogFlow

describe('TileCanvasLayoutError', () => {
    let flowLogic: ReturnType<typeof workflowLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': WORKFLOW,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await act(async () => {
            await flowLogic.asyncActions.loadWorkflow()
        })
        tileCanvasLogic({ id: WORKFLOW_ID }).mount()
    })

    afterEach(() => cleanup())

    const renderError = (): void => {
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <BindLogic logic={tileCanvasLogic} props={{ id: WORKFLOW_ID }}>
                        <TileCanvasLayoutError message="Maximum call stack size exceeded" />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    }

    it('points a saved workflow to its history instead of a retry that fails again', () => {
        renderError()

        expect(screen.getByText(/Your saved workflow did not change/)).toBeInTheDocument()
        expect(screen.getByText('Open history')).toBeInTheDocument()
        expect(screen.queryByText('Try again')).not.toBeInTheDocument()
    })

    it('offers to discard unsaved changes, and does not say the workflow is saved', () => {
        act(() => flowLogic.actions.setWorkflowValue('name', 'Renamed'))

        renderError()

        expect(screen.getByText(/Your unsaved changes are still here/)).toBeInTheDocument()
        expect(screen.getByText('Discard changes')).toBeInTheDocument()
        expect(screen.queryByText(/saved workflow did not change/)).not.toBeInTheDocument()
    })
})
