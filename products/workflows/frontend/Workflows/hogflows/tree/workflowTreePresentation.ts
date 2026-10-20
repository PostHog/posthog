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

export function getWorkflowTreeContinuationPath(tree: WorkflowTreeSequence, actionId: string): HogFlowEdge[] {
    const search = (sequence: WorkflowTreeSequence, path: HogFlowEdge[]): HogFlowEdge[] | null => {
        for (const node of sequence.nodes) {
            if (node.action.id === actionId) {
                return path
            }
            for (const branch of node.branches) {
                const found = search(branch.sequence, [...path, branch.edge])
                if (found) {
                    return found
                }
            }
        }
        return null
    }
    return search(tree, []) ?? []
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
    if (sequence.continueTo) {
        return `Continue to: ${sequence.continueTo.name}`
    }
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
    const continuation = branch.sequence.continueTo ?? node.joinAction
    const destination = continuation ? `Continue to: ${continuation.name}` : getPathDestination(branch.sequence)
    return `${count} ${count === 1 ? 'step' : 'steps'} · ${destination}`
}

export function getWorkflowTreeBranchKey(edge: HogFlowEdge): string {
    return `${edge.from}-${edge.type}-${edge.index ?? 'continue'}`
}

export interface WorkflowTreeBranchGroup {
    occurrenceKey: string
    branchKeys: string[]
}

function collectBranchGroups(
    sequence: WorkflowTreeSequence,
    path: HogFlowEdge[],
    groups: WorkflowTreeBranchGroup[]
): void {
    for (const node of sequence.nodes) {
        if (node.branches.length) {
            groups.push({
                occurrenceKey: getWorkflowTreeOccurrenceKey(node.action.id, path),
                branchKeys: node.branches.map((branch) => getWorkflowTreeBranchKey(branch.edge)),
            })
        }
        for (const branch of node.branches) {
            collectBranchGroups(branch.sequence, [...path, branch.edge], groups)
        }
    }
}

/** Every branching step in the tree, including the ones nested inside a path. */
export function getWorkflowTreeBranchGroups(sequence: WorkflowTreeSequence): WorkflowTreeBranchGroup[] {
    const groups: WorkflowTreeBranchGroup[] = []
    collectBranchGroups(sequence, [], groups)
    return groups
}

export function areAllWorkflowTreeBranchesCollapsed(
    groups: WorkflowTreeBranchGroup[],
    viewStates: Record<string, WorkflowTreeNodeViewState>
): boolean {
    return (
        groups.length > 0 &&
        groups.every((group) =>
            group.branchKeys.every((branchKey) => viewStates[group.occurrenceKey]?.collapsedBranches?.has(branchKey))
        )
    )
}
