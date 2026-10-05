import type { HogFlowEdge } from '../types'
import type { WorkflowTreeBranch, WorkflowTreeNode, WorkflowTreeSequence } from './workflowTree'

export const WORKFLOW_TREE_BRANCH_LIMIT = 6

export interface WorkflowTreePath {
    node: WorkflowTreeNode
    branch: WorkflowTreeBranch
}

export interface WorkflowTreeNodeViewState {
    branchesOpen?: boolean
    collapsedBranches?: Set<string>
    showAllBranches?: boolean
}

export function getWorkflowTreeOccurrenceKey(actionId: string, path: HogFlowEdge[]): string {
    return encodeURIComponent(JSON.stringify([path.map((edge) => [edge.from, edge.type, edge.index]), actionId]))
}

export function getWorkflowTreeStepId(actionId: string, path: HogFlowEdge[]): string {
    return `workflow-tree-step-${actionId}${path.length ? `-${getWorkflowTreeOccurrenceKey(actionId, path)}` : ''}`
}

export function findWorkflowTreePath(sequence: WorkflowTreeSequence, edges: HogFlowEdge[]): WorkflowTreePath[] {
    const [edge, ...remainingEdges] = edges
    if (!edge) {
        return []
    }
    for (const node of sequence.nodes) {
        for (const branch of node.branches) {
            const path = { node, branch }
            if (branch.edge.from === edge.from && branch.edge.type === edge.type && branch.edge.index === edge.index) {
                if (remainingEdges.length === 0) {
                    return [path]
                }
                const nestedPath = findWorkflowTreePath(branch.sequence, remainingEdges)
                return nestedPath.length ? [path, ...nestedPath] : []
            }
        }
    }
    return []
}

export function getWorkflowTreeContinuationPath(
    tree: WorkflowTreeSequence,
    path: HogFlowEdge[],
    actionId: string
): HogFlowEdge[] {
    for (let depth = path.length; depth > 0; depth--) {
        const ancestorPath = path.slice(0, depth)
        const sequence = findWorkflowTreePath(tree, ancestorPath).at(-1)?.branch.sequence
        if (sequence?.nodes.some((node) => node.action.id === actionId)) {
            return ancestorPath
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
