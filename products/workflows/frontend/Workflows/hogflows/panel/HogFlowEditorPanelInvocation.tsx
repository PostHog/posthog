import { useValues } from 'kea'

import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { renderWorkflowLogMessage } from '../../logs/log-utils'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelInvocation({ instanceId }: { instanceId: string }): JSX.Element {
    const { workflow, selectedNode } = useValues(hogFlowEditorLogic)

    const actionId = selectedNode?.data.id

    return (
        <div className="p-2 flex flex-col gap-2 overflow-y-auto">
            <LogsViewer
                logicKey={`invocation-panel-${instanceId}-${actionId || 'all'}`}
                instanceLabel="workflow run"
                sourceType="hog_flow"
                sourceId={workflow.id}
                groupByInstanceId={false}
                defaultFilters={{ instanceId }}
                searchGroups={actionId ? [`[Action:${actionId}]`] : undefined}
                renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
                hideDateFilter
            />
        </div>
    )
}
