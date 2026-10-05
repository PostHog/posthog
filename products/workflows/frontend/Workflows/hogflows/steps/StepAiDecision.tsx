import { Node } from '@xyflow/react'

import { AiDecisionAction } from './aiDecisionBranches'

export function StepAiDecisionConfiguration({ node }: { node: Node<AiDecisionAction> }): JSX.Element {
    return <div>{node.data.config.question}</div>
}
