import clsx from 'clsx'
import { useValues } from 'kea'
import type { CSSProperties } from 'react'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'
import { HogFlowEditorPanelSelectedStep } from './HogFlowEditorPanelSelectedStep'

export function HogFlowEditorPanelStep({
    className,
    style,
}: {
    className?: string
    style?: CSSProperties
}): JSX.Element | null {
    const { selectedNode } = useValues(hogFlowEditorLogic)

    if (!selectedNode) {
        return null
    }

    return (
        <div
            className={clsx('flex min-h-0 flex-col overflow-hidden rounded-md border bg-surface-primary', className)}
            style={style}
            data-attr="workflow-editor-panel"
        >
            <HogFlowEditorPanelSelectedStep />
            <HogFlowEditorPanelBuildDetail />
        </div>
    )
}
