import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelLogs } from './HogFlowEditorPanelLogs'

describe('HogFlowEditorPanelLogs', () => {
    let logic: ReturnType<typeof workflowLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/:id/': { ...NEW_WORKFLOW, id: 'template-1' },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        logic?.unmount()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it.each([
        ['a blank workflow', { id: 'new' }],
        ['a workflow made from a template', { id: 'new', templateId: 'template-1' }],
    ])('asks to save %s before showing logs, without querying them', async (_, props: WorkflowLogicProps) => {
        const queryHogQL = jest.spyOn(api, 'queryHogQL')
        logic = workflowLogic(props)
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadWorkflowSuccess'])
        jest.useFakeTimers()

        render(
            <Provider>
                <BindLogic logic={workflowLogic} props={props}>
                    <BindLogic logic={hogFlowEditorLogic} props={props}>
                        <HogFlowEditorPanelLogs />
                    </BindLogic>
                </BindLogic>
            </Provider>
        )
        // Runs past the logs loader's debounce, where a mounted viewer would send its query.
        await act(async () => {
            await jest.advanceTimersByTimeAsync(1000)
        })

        expect(screen.getByText('Logs appear here after you save the workflow.')).toBeInTheDocument()
        expect(queryHogQL).not.toHaveBeenCalled()
    })
})
