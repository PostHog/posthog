import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { urls } from 'scenes/urls'

import { renderWorkflowLogMessage } from '../../logs/log-utils'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelLogs(): JSX.Element | null {
    const { workflow, selectedNode } = useValues(hogFlowEditorLogic)

    const actionId = selectedNode?.data.id

    const shouldShowActionLevelLogs = workflow.trigger?.type !== 'batch'

    if (!workflow.id || workflow.id === 'new') {
        return <div className="p-4 text-center text-secondary">Save the workflow to see its logs.</div>
    }

    return (
        <>
            <div className="border-b">
                <LemonButton to={urls.workflow(workflow.id, 'logs')} size="xsmall" sideIcon={<IconOpenInApp />}>
                    {shouldShowActionLevelLogs
                        ? 'Click here to open in full log viewer'
                        : 'Click here to open batch workflow invocations tab'}
                </LemonButton>
            </div>
            {shouldShowActionLevelLogs && (
                <div className="p-2 flex flex-col gap-2 overflow-y-auto">
                    <LogsViewer
                        logicKey={`hog-flow-editor-panel-${actionId || 'all'}`}
                        instanceLabel="workflow run"
                        sourceType="hog_flow"
                        sourceId={workflow.id}
                        groupByInstanceId={!selectedNode}
                        searchGroups={actionId ? [`[Action:${actionId}]`] : undefined}
                        renderMessage={(m) => renderWorkflowLogMessage(workflow, m)}
                    />
                </div>
            )}
        </>
    )
}
