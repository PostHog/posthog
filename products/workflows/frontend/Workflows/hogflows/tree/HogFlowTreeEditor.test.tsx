import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { ReactFlowProvider } from '@xyflow/react'
import { BindLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { EXIT_NODE_ID, NEW_WORKFLOW, TRIGGER_NODE_ID, workflowLogic } from '../../workflowLogic'
import { HogFlowBranchSelectionProvider } from '../HogFlowBranchSelection'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { DELAY_NODES_TO_SHOW } from '../stepPicker/stepDefinitions'
import { HogFlowTreeEditor } from './HogFlowTreeEditor'

const LOGIC_PROPS = { id: 'new' }

describe('HogFlowTreeEditor', () => {
    const editorLogic = (): ReturnType<typeof hogFlowEditorLogic.build> => hogFlowEditorLogic(LOGIC_PROPS)

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_STEP_PICKER], {
            [FEATURE_FLAGS.WORKFLOWS_STEP_PICKER]: true,
        })
        editorLogic().mount()
        workflowLogic(LOGIC_PROPS).actions.setWorkflowInfo({
            actions: NEW_WORKFLOW.actions,
            edges: [{ from: TRIGGER_NODE_ID, to: EXIT_NODE_ID, type: 'continue' }],
        })
        render(
            <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
                <BindLogic logic={hogFlowEditorLogic} props={LOGIC_PROPS}>
                    <HogFlowBranchSelectionProvider>
                        <ReactFlowProvider>
                            <HogFlowTreeEditor />
                        </ReactFlowProvider>
                    </HogFlowBranchSelectionProvider>
                </BindLogic>
            </BindLogic>
        )
        editorLogic().actions.startPlacingNewStep(DELAY_NODES_TO_SHOW[0])
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { target: 'a step', element: () => document.querySelector('[data-attr="workflow-tree-step"]'), placing: true },
        {
            target: 'the empty tree area',
            element: () => document.querySelector('[data-attr="workflow-tree-editor"] .group\\/tree'),
            placing: false,
        },
    ])('keeps placing a new step only when the click lands on $target', ({ element, placing }) => {
        fireEvent.click(element() as HTMLElement)

        expect(editorLogic().values.isPlacingNewStep).toBe(placing)
    })
})
