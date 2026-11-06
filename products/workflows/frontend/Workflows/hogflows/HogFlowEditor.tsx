import '@xyflow/react/dist/style.css'

import { ReactFlowProvider } from '@xyflow/react'
import { BindLogic, useValues } from 'kea'

import { workflowLogic } from '../workflowLogic'
import { TileCanvas } from './editor/tile-canvas/TileCanvas'
import { HogFlowBranchSelectionProvider } from './HogFlowBranchSelection'
import { hogFlowEditorLogic } from './hogFlowEditorLogic'

export function HogFlowEditor(): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    return (
        <BindLogic logic={hogFlowEditorLogic} props={logicProps}>
            <HogFlowBranchSelectionProvider>
                <div className="@container/workflow-editor flex min-h-0 min-w-0 flex-1">
                    <ReactFlowProvider>
                        <TileCanvas />
                    </ReactFlowProvider>
                </div>
            </HogFlowBranchSelectionProvider>
        </BindLogic>
    )
}
