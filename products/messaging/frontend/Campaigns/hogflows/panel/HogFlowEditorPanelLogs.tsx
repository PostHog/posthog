import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { IconOpenInApp } from 'lib/lemon-ui/icons'
import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'
import { urls } from 'scenes/urls'

import { renderWorkflowLogMessage } from '../../logs/log-utils'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelLogs(): JSX.Element | null {
    const { campaign, selectedNode } = useValues(hogFlowEditorLogic)

    const actionId = selectedNode?.data.id

    return (
        <>
            <div className="border-b">
                <LemonButton
                    to={urls.messagingCampaign(campaign.id, 'logs')}
                    size="xsmall"
                    sideIcon={<IconOpenInApp />}
                >
                    Click here to open in full log viewer
                </LemonButton>
            </div>
            <div className="p-2 flex flex-col gap-2 overflow-y-auto">
                <LogsViewer
                    logicKey={`hog-flow-editor-panel-${actionId || 'all'}`}
                    instanceLabel="workflow run"
                    sourceType="hog_flow"
                    sourceId={campaign.id}
                    groupByInstanceId={!selectedNode}
                    searchGroups={actionId ? [`[Action:${actionId}]`] : undefined}
                    // renderColumns={(columns) => columns.filter((c) => c.key !== 'instanceId')}
                    renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
                />
            </div>
        </>
    )
}
