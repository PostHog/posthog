import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { workflowLogic } from '../../../workflowLogic'
import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'
import type { HogFlow, HogFlowAction } from '../../types'
import { tileCanvasLogic } from './tileCanvasLogic'
import { TileStepMenu } from './TileStepMenu'

jest.mock('lib/components/AppMetrics/appMetricsLogic', () => ({
    ...jest.requireActual('lib/components/AppMetrics/appMetricsLogic'),
    loadAppMetricsTotals: () => new Promise(() => {}),
}))

const WORKFLOW_ID = 'wf-menu-1'
const SYNC = { id: 'sync', type: 'delay', name: 'Wait', config: { delay_duration: '1d' } } as unknown as HogFlowAction

const WORKFLOW = {
    id: WORKFLOW_ID,
    name: 'Menu test',
    version: 1,
    status: 'draft',
    team_id: 1,
    exit_condition: 'exit_only_at_end',
    trigger: { type: 'event', filters: {} },
    actions: [
        { id: 'trigger_node', type: 'trigger', name: 'Trigger', config: { type: 'event', filters: {} } },
        SYNC,
        { id: 'exit_node', type: 'exit', name: 'Exit', config: { reason: '' } },
    ],
    edges: [
        { from: 'trigger_node', to: 'sync', type: 'continue' },
        { from: 'sync', to: 'exit_node', type: 'continue' },
    ],
    created_at: '2026-10-01T00:00:00.000Z',
    updated_at: '2026-10-01T00:00:00.000Z',
} as unknown as HogFlow

describe('TileStepMenu', () => {
    let canvasLogic: ReturnType<typeof tileCanvasLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/hog_flows/:id/': WORKFLOW,
                '/api/projects/:team_id/hog_function_templates/': { results: [], count: 0 },
            },
        })
        initKeaTests()
        const flowLogic = workflowLogic({ id: WORKFLOW_ID })
        flowLogic.mount()
        await act(async () => {
            await flowLogic.asyncActions.loadWorkflow()
        })
        canvasLogic = tileCanvasLogic({ id: WORKFLOW_ID })
        canvasLogic.mount()
        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={{ id: WORKFLOW_ID }}>
                    <BindLogic logic={tileCanvasLogic} props={{ id: WORKFLOW_ID }}>
                        {/* React Flow puts keyboard focus on the node wrapper, which carries the node id. */}
                        <div className="react-flow__node" data-id="sync" tabIndex={0}>
                            <TileStepMenu action={SYNC}>
                                <div>Wait</div>
                            </TileStepMenu>
                        </div>
                        <button type="button">Elsewhere</button>
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
    })

    afterEach(() => cleanup())

    const openFromKeyboard = async (): Promise<HTMLElement> => {
        const tile = document.querySelector<HTMLElement>('[data-id="sync"]')!
        await waitFor(() => expect(hogFlowEditorLogic({ id: WORKFLOW_ID }).values.edges.length).toBeGreaterThan(0))
        tile.focus()
        act(() => canvasLogic.actions.openStepMenu('sync', true))
        await waitFor(() => expect(screen.getByText('Copy').closest('button')).toHaveFocus())
        return tile
    }

    it('moves focus to the first item when the menu opens from the keyboard, and back to the tile on Escape', async () => {
        const tile = await openFromKeyboard()

        fireEvent.keyDown(document.activeElement!, { key: 'Escape' })

        await waitFor(() => expect(tile).toHaveFocus())
        expect(canvasLogic.values.stepMenuActionId).toBeNull()
    })

    it('closes the menu when focus leaves it', async () => {
        await openFromKeyboard()

        act(() => screen.getByText('Elsewhere').focus())

        await waitFor(() => expect(canvasLogic.values.stepMenuActionId).toBeNull())
    })
})
