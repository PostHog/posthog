import { Node } from '@xyflow/react'
import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'

import { HogFlowAction } from '../types'
import type { nodeLogicType } from './nodeLogicType'

export interface NodeLogicProps {
    node: Node<HogFlowAction>
}

export const nodeLogic = kea<nodeLogicType>([
    path(['products', 'messaging', 'frontend', 'Campaigns', 'Workflows', 'Nodes', 'nodeLogic']),
    props({ node: {} } as NodeLogicProps),
    key((props) => props.node.id),
    forms(({ props }) => ({
        inputs: {
            defaults: {
                ...props.node.data.config.inputs,
            },
        },
    })),
])
