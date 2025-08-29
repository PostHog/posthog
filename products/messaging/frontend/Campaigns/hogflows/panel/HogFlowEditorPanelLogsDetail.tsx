import { useValues } from 'kea'

import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { renderWorkflowLogMessage } from '../../logs/log-utils'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelLogsDetail(): JSX.Element | null {
    const { selectedNode, campaign } = useValues(hogFlowEditorLogic)

    return (
        <div className="p-2 flex flex-col gap-2 overflow-hidden">
            <LogsViewer
                sourceType="hog_flow"
                sourceId={campaign.id}
                renderColumns={(columns) => columns.filter((c) => c.key !== 'instanceId')}
                renderMessage={(m) => renderWorkflowLogMessage(campaign, m)}
            />
        </div>
    )
}
