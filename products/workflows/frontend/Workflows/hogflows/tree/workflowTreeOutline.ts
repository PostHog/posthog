import type { HogFlowEdge } from '../types'
import type { WorkflowTreeBranch, WorkflowTreeNode, WorkflowTreeSequence } from './workflowTree'
import {
    getWorkflowTreeBranchBadge,
    getWorkflowTreeBranchIndex,
    getWorkflowTreePathHeaderId,
    getWorkflowTreeStepId,
    getWorkflowTreeStepIds,
} from './workflowTreePresentation'

export interface WorkflowTreeOutlineRow {
    key: string
    kind: 'step' | 'path'
    depth: number
    label: string
    node: WorkflowTreeNode
    branch: WorkflowTreeBranch | null
    branchIndex: number | null
    badge: string | null
    // For a step, the edges from the trigger to the sequence that holds it. For a path, the edges
    // up to and including the path itself.
    path: HogFlowEdge[]
    // The element id the row scrolls to: the step card or the path header.
    targetId: string
    stepCount: number | null
}

export function buildWorkflowTreeOutline(
    sequence: WorkflowTreeSequence,
    path: HogFlowEdge[] = [],
    depth = 0
): WorkflowTreeOutlineRow[] {
    const rows: WorkflowTreeOutlineRow[] = []
    for (const node of sequence.nodes) {
        const stepId = getWorkflowTreeStepId(node.action.id, path)
        rows.push({
            key: stepId,
            kind: 'step',
            depth,
            label: node.action.name,
            node,
            branch: null,
            branchIndex: null,
            badge: null,
            path,
            targetId: stepId,
            stepCount: null,
        })
        node.branches.forEach((branch, position) => {
            const branchPath = [...path, branch.edge]
            const branchIndex = getWorkflowTreeBranchIndex(branch, position)
            const headerId = getWorkflowTreePathHeaderId(node.action.id, branchPath)
            rows.push({
                key: headerId,
                kind: 'path',
                depth: depth + 1,
                label: branch.label,
                node,
                branch,
                branchIndex,
                badge: getWorkflowTreeBranchBadge(node, branchIndex),
                path: branchPath,
                targetId: headerId,
                stepCount: getWorkflowTreeStepIds(branch.sequence).size,
            })
            rows.push(...buildWorkflowTreeOutline(branch.sequence, branchPath, depth + 2))
        })
    }
    return rows
}

export function filterWorkflowTreeOutline(rows: WorkflowTreeOutlineRow[], query: string): WorkflowTreeOutlineRow[] {
    const needle = query.trim().toLowerCase()
    if (!needle) {
        return rows
    }
    return rows.filter((row) => row.label.toLowerCase().includes(needle))
}
