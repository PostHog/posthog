import { Edge, Handle, Node, NodeProps } from '@xyflow/react'

import { Optional } from '~/types'

import { HogFlowAction } from '../types'

export type HogFlowStepNodeProps = NodeProps & {
    data: HogFlowAction
    type: HogFlowAction['type']
}

export type StepViewNodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

export type HogFlowStep<T extends HogFlowAction['type']> = {
    type: T
    renderNode: (props: HogFlowStepNodeProps) => JSX.Element
    renderConfiguration: (node: Node<Extract<HogFlowAction, { type: T }>>) => JSX.Element
    create: (edgeToInsertNodeInto: Edge) => Pick<Extract<HogFlowAction, { type: T }>, 'config' | 'name' | 'description'>
    getHandles: (action: Extract<HogFlowAction, { type: T }>) => StepViewNodeHandle[]
}
