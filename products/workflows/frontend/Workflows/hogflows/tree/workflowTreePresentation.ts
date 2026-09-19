import type { HogFlowEdge } from '../types'
import type { WorkflowTreeBranch, WorkflowTreeNode, WorkflowTreeSequence } from './workflowTree'

export interface WorkflowTreePath {
    node: WorkflowTreeNode
    branch: WorkflowTreeBranch
}

export function findWorkflowTreePath(sequence: WorkflowTreeSequence, edge: HogFlowEdge): WorkflowTreePath[] {
    for (const node of sequence.nodes) {
        for (const branch of node.branches) {
            const path = { node, branch }
            if (branch.edge.from === edge.from && branch.edge.type === edge.type && branch.edge.index === edge.index) {
                return [path]
            }
            const nestedPath = findWorkflowTreePath(branch.sequence, edge)
            if (nestedPath.length > 0) {
                return [path, ...nestedPath]
            }
        }
    }
    return []
}

function collectStepIds(sequence: WorkflowTreeSequence, stepIds: Set<string>): void {
    for (const node of sequence.nodes) {
        stepIds.add(node.action.id)
        for (const branch of node.branches) {
            collectStepIds(branch.sequence, stepIds)
        }
    }
}

export function getWorkflowTreeStepIds(sequence: WorkflowTreeSequence): Set<string> {
    const stepIds = new Set<string>()
    collectStepIds(sequence, stepIds)
    return stepIds
}

function getPathDestination(sequence: WorkflowTreeSequence): string {
    const lastNode = sequence.nodes.at(-1)
    if (lastNode?.action.type === 'exit') {
        return 'End workflow'
    }
    if (lastNode?.branches.length) {
        const destinations = new Set(lastNode.branches.map((branch) => getPathDestination(branch.sequence)))
        return destinations.size === 1 ? [...destinations][0] : 'Paths have different destinations'
    }
    return 'No next step'
}

export function getWorkflowTreeBranchSummary(node: WorkflowTreeNode, branch: WorkflowTreeBranch): string {
    const count = getWorkflowTreeStepIds(branch.sequence).size
    const destination = node.joinAction ? `Continue to: ${node.joinAction.name}` : getPathDestination(branch.sequence)
    return `${count} ${count === 1 ? 'step' : 'steps'} · ${destination}`
}
