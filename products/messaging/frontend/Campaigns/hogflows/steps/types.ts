import { Node, NodeProps } from '@xyflow/react'

import { HogFlowAction } from '../types'

export type HogFlowStepNodeProps = NodeProps & {
    data: HogFlowAction
    type: HogFlowAction['type']
}

export type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    renderNode: (props: HogFlowStepNodeProps) => JSX.Element
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
}
