import { useValues } from 'kea'

import { hogFlowEditorLogic } from '../../hogFlowEditorLogic'

export type HogFlowEditorPanelNodeRequiredProps = {
    children: React.ReactNode
}

export function HogFlowEditorPanelNodeRequired({ children }: HogFlowEditorPanelNodeRequiredProps): JSX.Element {
    const { selectedNode } = useValues(hogFlowEditorLogic)

    if (selectedNode) {
        return <>{children}</>
    }

    return (
        <div className="p-2">
            <div className="p-8 text-center rounded border bg-surface-secondary">
                <div className="text-muted">Please select an action...</div>
            </div>
        </div>
    )
}
