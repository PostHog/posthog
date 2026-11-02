import type { HogFlowActionApi, HogFlowEdgeApi } from '../../../../../generated/api.schemas'

export interface WorkflowCanvasPreviewProps {
    actions: HogFlowActionApi[]
    edges: HogFlowEdgeApi[]
    exitCondition?: string | null
    isDarkModeOn: boolean
}
