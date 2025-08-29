import { useValues } from 'kea'

import { LogsViewer } from 'scenes/hog-functions/logs/LogsViewer'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelLogsDetail(): JSX.Element | null {
    const { selectedNode, campaign } = useValues(hogFlowEditorLogic)
    const id = selectedNode?.data.id ?? 'unknown'

    return (
        <div className="p-2 flex flex-col gap-2 overflow-hidden">
            <LogsViewer sourceType="hog_flow" sourceId={campaign.id} />
        </div>
    )
}
